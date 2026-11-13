#!/usr/bin/env node
/**
 * export_dex.js
 *
 * Exports everything the team builder needs to know about a Pokemon Champions
 * regulation set - legal species (including Megas and Z-Megas), their legal
 * movepools, legal held items, move/ability/item text, natures and the type
 * chart - straight from Pokemon Showdown's `champions` mod.
 *
 * Showdown is the source of truth here because its team validator is what
 * actually decides legality on the ladder, so the tool can never drift from it.
 *
 * Usage (requires a built Pokemon Showdown checkout, see README):
 *   node scripts/export_dex.js --ps ../pokemon-showdown --out data/dex
 *
 * Writes one JSON file per regulation, e.g. data/dex/regmc.json.
 */

'use strict';

const fs = require('fs');
const path = require('path');

const args = process.argv.slice(2);
function arg(name, fallback) {
	const i = args.indexOf(`--${name}`);
	return i >= 0 ? args[i + 1] : fallback;
}

const psPath = path.resolve(arg('ps', '../pokemon-showdown'));
const outDir = path.resolve(arg('out', 'data/dex'));
const { Dex, TeamValidator } = require(path.join(psPath, 'dist', 'sim'));
const TEXT = {
	items: require(path.join(psPath, 'dist', 'data', 'text', 'items')).ItemsText,
	moves: require(path.join(psPath, 'dist', 'data', 'text', 'moves')).MovesText,
	abilities: require(path.join(psPath, 'dist', 'data', 'text', 'abilities')).AbilitiesText,
};
// Descriptions live in Showdown's text tables, not on the data objects.
function describe(table, id) {
	const entry = TEXT[table][id] || {};
	return entry.shortDesc || entry.desc || '';
}

// Regulation key -> the Showdown format whose rules define legality.
// Singles (BSS) and doubles (VGC) share a legal pool within a regulation, so
// one dex file per regulation is enough.
const REGULATIONS = {
	regmc: 'gen9championsvgc2026regmc',
	regmb: 'gen9championsvgc2026regmb',
};

const SPREAD_TARGETS = new Set(['allAdjacentFoes', 'allAdjacent']);
const KEPT_FLAGS = ['contact', 'sound', 'punch', 'bite', 'slicing', 'pulse', 'heal', 'wind', 'bullet'];

function exportRegulation(regKey, formatId) {
	const format = Dex.formats.get(formatId);
	if (!format.exists) {
		console.warn(`skipping ${regKey}: format ${formatId} not found in this Showdown build`);
		return;
	}
	const dex = Dex.forFormat(format);
	const ruleTable = dex.formats.getRuleTable(format);
	const validator = TeamValidator.get(format);

	const isLegalSpecies = s => s.exists && !s.isNonstandard && s.tier !== 'Illegal' &&
		!ruleTable.isBannedSpecies(s);
	const legalSpecies = dex.species.all().filter(isLegalSpecies);

	const usedMoves = new Set();
	const species = {};
	for (const s of legalSpecies) {
		// Megas and battle-only formes learn whatever their base forme learns.
		const learnFrom = (s.isMega || s.battleOnly) ? dex.species.get(s.battleOnly || s.baseSpecies) : s;
		const learnset = dex.moves.all()
			.filter(m => !m.isNonstandard && !validator.checkCanLearn(m, learnFrom))
			.map(m => m.id)
			.sort();
		learnset.forEach(id => usedMoves.add(id));
		species[s.id] = {
			id: s.id,
			name: s.name,
			num: s.num,
			baseSpecies: s.baseSpecies,
			forme: s.forme || '',
			types: s.types,
			baseStats: s.baseStats,
			abilities: Object.values(s.abilities).filter(Boolean),
			weightkg: s.weightkg,
			isMega: !!s.isMega,
			battleOnly: s.battleOnly ? [].concat(s.battleOnly) : [],
			requiredItem: s.requiredItem || null,
			sprite: s.spriteid,
			// Showdown's own tiering for this mod, a rough "how good is it" label.
			tier: s.tier,
			doublesTier: s.doublesTier,
			learnset,
		};
	}

	const items = {};
	for (const it of dex.items.all()) {
		if (!it.exists || it.isNonstandard || ruleTable.isBanned(`item:${it.id}`)) continue;
		items[it.id] = {
			id: it.id,
			name: it.name,
			desc: describe('items', it.id),
			// {"Garchomp": "Garchomp-Mega-Z"} for Mega Stones, else null
			megaStone: it.megaStone || null,
			isBerry: !!it.isBerry,
		};
	}

	const moves = {};
	for (const id of usedMoves) {
		const m = dex.moves.get(id);
		moves[id] = {
			id: m.id,
			name: m.name,
			type: m.type,
			category: m.category,
			basePower: m.basePower,
			accuracy: m.accuracy === true ? null : m.accuracy,
			priority: m.priority,
			pp: m.pp,
			target: m.target,
			spread: SPREAD_TARGETS.has(m.target),
			flags: KEPT_FLAGS.filter(f => m.flags[f]),
			desc: describe('moves', m.id),
		};
	}

	const abilityIds = new Set();
	Object.values(species).forEach(s => s.abilities.forEach(a => abilityIds.add(dex.abilities.get(a).id)));
	const abilities = {};
	for (const id of abilityIds) {
		const a = dex.abilities.get(id);
		abilities[id] = { id: a.id, name: a.name, desc: describe('abilities', a.id) };
	}

	const natures = {};
	for (const n of dex.natures.all()) {
		natures[n.id] = { name: n.name, plus: n.plus || null, minus: n.minus || null };
	}

	// typechart[attacking][defending] = multiplier
	const typeNames = dex.types.all().filter(t => !t.isNonstandard).map(t => t.name);
	const typechart = {};
	for (const atk of typeNames) {
		typechart[atk] = {};
		for (const def of typeNames) {
			const code = dex.types.get(def).damageTaken[atk];
			typechart[atk][def] = [1, 2, 0.5, 0][code ?? 0];
		}
	}

	const out = {
		regulation: regKey,
		formatId,
		formatName: format.name,
		generatedAt: new Date().toISOString().slice(0, 10),
		rules: {
			level: 50,
			statPointTotal: ruleTable.evLimit ?? 66,
			statPointMax: 32,
			itemClause: true,
			speciesClause: true,
			megaPerBattle: 1,
		},
		species,
		items,
		moves,
		abilities,
		natures,
		typechart,
	};
	fs.mkdirSync(outDir, { recursive: true });
	const file = path.join(outDir, `${regKey}.json`);
	fs.writeFileSync(file, JSON.stringify(out));
	console.log(`${regKey}: ${Object.keys(species).length} species, ${Object.keys(items).length} items, ` +
		`${Object.keys(moves).length} moves -> ${path.relative(process.cwd(), file)}`);
}

for (const [key, formatId] of Object.entries(REGULATIONS)) exportRegulation(key, formatId);
