#!/usr/bin/env node
/**
 * make_damage_vectors.js
 *
 * Generates test vectors for src/damage.py by running Pokemon Showdown's own
 * damage code (battle.actions.getDamage) for many attacker / defender / move /
 * field combinations and recording all 16 damage rolls.
 *
 *   node scripts/make_damage_vectors.js --ps ../pokemon-showdown > tests/fixtures/damage_vectors.json
 */
'use strict';

const path = require('path');
const args = process.argv.slice(2);
const psPath = path.resolve(args[args.indexOf('--ps') + 1] || '../pokemon-showdown');
const { Battle, Teams, Dex } = require(path.join(psPath, 'dist', 'sim'));

const FORMATS = { doubles: 'gen9championsvgc2026regmc', singles: 'gen9championsbssregmc' };

// Sets: [species, item, ability, nature, SPs {hp,atk,def,spa,spd,spe}]
const SETS = {
	garganacl: ['Garganacl', 'Leftovers', 'Purifying Salt', 'Careful', { hp: 32, def: 2, spd: 32 }],
	chompz: ['Garchomp-Mega-Z', 'Garchompite Z', 'Levitate', 'Timid', { hp: 2, spa: 32, spe: 32 }],
	rilla: ['Rillaboom', 'Miracle Seed', 'Grassy Surge', 'Adamant', { hp: 32, atk: 32, spd: 2 }],
	incin: ['Incineroar', 'Sitrus Berry', 'Intimidate', 'Careful', { hp: 32, atk: 2, spd: 32 }],
	ghold: ['Gholdengo', 'Life Orb', 'Good as Gold', 'Modest', { hp: 2, spa: 32, spe: 32 }],
	sneasler: ['Sneasler', 'Focus Sash', 'Unburden', 'Jolly', { hp: 2, atk: 32, spe: 32 }],
	zardy: ['Charizard-Mega-Y', 'Charizardite Y', 'Drought', 'Modest', { hp: 2, spa: 32, spe: 32 }],
	kingambit: ['Kingambit', 'Black Glasses', 'Defiant', 'Adamant', { hp: 32, atk: 32, spd: 2 }],
	farigiraf: ['Farigiraf', 'Sitrus Berry', 'Armor Tail', 'Relaxed', { hp: 32, def: 32, spd: 2 }],
	sinistcha: ['Sinistcha', 'Mental Herb', 'Hospitality', 'Bold', { hp: 32, def: 32, spd: 2 }],
	basc: ['Basculegion', 'Mystic Water', 'Adaptability', 'Adamant', { hp: 2, atk: 32, spe: 32 }],
	archaludon: ['Archaludon', 'Assault Vest', 'Stamina', 'Modest', { hp: 32, spa: 32, spd: 2 }],
	whimsi: ['Whimsicott', 'Focus Sash', 'Prankster', 'Timid', { hp: 32, spd: 2, spe: 32 }],
	dnite: ['Dragonite', 'Expert Belt', 'Multiscale', 'Adamant', { hp: 32, atk: 32, spe: 2 }],
	tyranitar: ['Tyranitar', 'Chople Berry', 'Sand Stream', 'Adamant', { hp: 32, atk: 32, spd: 2 }],
	sylveon: ['Gardevoir-Mega', 'Gardevoirite', 'Pixilate', 'Modest', { hp: 32, spa: 32, spe: 2 }],
	feraligatr: ['Feraligatr-Mega', 'Feraligatrite', 'Dragonize', 'Adamant', { hp: 2, atk: 32, spe: 32 }],
	scizor: ['Scizor', 'Metal Coat', 'Technician', 'Adamant', { hp: 32, atk: 32, spd: 2 }],
	lucario: ['Lucario-Mega-Z', 'Lucarionite Z', 'Aura Guard', 'Timid', { hp: 2, spa: 32, spe: 32 }],
};

const CASES = [
	// attacker, defender, move, field options
	['garganacl', 'incin', 'Body Press', {}],
	['garganacl', 'rilla', 'Salt Cure', {}],
	['garganacl', 'kingambit', 'Body Press', { atkBoost: { def: 2 } }],
	['chompz', 'garganacl', 'Earth Power', {}],
	['chompz', 'incin', 'Draco Meteor', {}],
	['chompz', 'zardy', 'Earth Power', {}],
	['chompz', 'farigiraf', 'Flamethrower', { weather: 'sunnyday' }],
	['rilla', 'garganacl', 'Wood Hammer', {}],
	['rilla', 'garganacl', 'Grassy Glide', { terrain: 'grassyterrain' }],
	['rilla', 'basc', 'Wood Hammer', { terrain: 'grassyterrain', helpingHand: true }],
	['rilla', 'incin', 'Wood Hammer', { atkBoostMinus: 1 }],
	['incin', 'ghold', 'Flare Blitz', {}],
	['incin', 'sinistcha', 'Flare Blitz', { weather: 'sunnyday' }],
	['incin', 'sinistcha', 'Flare Blitz', { weather: 'raindance' }],
	['ghold', 'garganacl', 'Make It Rain', { spread: true }],
	['ghold', 'sinistcha', 'Shadow Ball', {}],
	['ghold', 'garganacl', 'Shadow Ball', {}],
	['ghold', 'farigiraf', 'Shadow Ball', { screen: true }],
	['ghold', 'farigiraf', 'Shadow Ball', { crit: true }],
	['sneasler', 'kingambit', 'Close Combat', {}],
	['sneasler', 'garganacl', 'Close Combat', {}],
	['sneasler', 'incin', 'Close Combat', { atkBoostMinus: 1, crit: true }],
	['zardy', 'rilla', 'Heat Wave', { spread: true, weather: 'sunnyday' }],
	['zardy', 'garganacl', 'Heat Wave', { spread: true, weather: 'sunnyday' }],
	['zardy', 'sinistcha', 'Solar Beam', { weather: 'sunnyday' }],
	['zardy', 'archaludon', 'Weather Ball', { weather: 'sunnyday' }],
	['kingambit', 'ghold', 'Kowtow Cleave', {}],
	['kingambit', 'sinistcha', 'Sucker Punch', {}],
	['kingambit', 'farigiraf', 'Knock Off', {}],
	['farigiraf', 'sneasler', 'Psychic', {}],
	['farigiraf', 'sneasler', 'Psychic', { terrain: 'psychicterrain' }],
	['sinistcha', 'basc', 'Matcha Gotcha', { spread: true }],
	['basc', 'garganacl', 'Wave Crash', {}],
	['basc', 'zardy', 'Wave Crash', { weather: 'raindance' }],
	['basc', 'incin', 'Aqua Jet', {}],
	['archaludon', 'basc', 'Electro Shot', { weather: 'raindance' }],
	['archaludon', 'garganacl', 'Flash Cannon', { sand: true }],
	['archaludon', 'tyranitar', 'Flash Cannon', { weather: 'sandstorm' }],
	['whimsi', 'kingambit', 'Moonblast', {}],
	['dnite', 'chompz', 'Extreme Speed', {}],
	['chompz', 'dnite', 'Draco Meteor', {}],
	['dnite', 'garganacl', 'Earthquake', { spread: true, terrain: 'grassyterrain' }],
	['dnite', 'tyranitar', 'Iron Head', {}],
	['tyranitar', 'zardy', 'Rock Slide', { spread: true }],
	['incin', 'tyranitar', 'Close Combat', {}],
	['sylveon', 'chompz', 'Hyper Voice', { spread: true }],
	['sylveon', 'kingambit', 'Hyper Voice', { spread: true }],
	['feraligatr', 'garganacl', 'Double-Edge', {}],
	['scizor', 'whimsi', 'Bullet Punch', {}],
	['scizor', 'sylveon', 'Bullet Punch', { atkBoost: { atk: 2 } }],
	['lucario', 'kingambit', 'Aura Sphere', {}],
	['incin', 'lucario', 'Flare Blitz', {}],
	['incin', 'farigiraf', 'Foul Play', {}],
	['whimsi', 'farigiraf', 'Psyshock', {}],
	['garganacl', 'sneasler', 'Salt Cure', { defBoost: { def: -1 } }],
	['ghold', 'garganacl', 'Make It Rain', { spread: true, screen: true }],
];

function setFor(key) {
	const [species, item, ability, nature, sps] = SETS[key];
	return { name: species, species, item, ability, nature, evs: { hp: 0, atk: 0, def: 0, spa: 0, spd: 0, spe: 0, ...sps },
		ivs: { hp: 31, atk: 31, def: 31, spa: 31, spd: 31, spe: 31 }, moves: ['protect'], level: 50, gender: '' };
}

const WEATHER = { sunnyday: 'sun', raindance: 'rain', sandstorm: 'sand', snowscape: 'snow' };
const TERRAIN = { grassyterrain: 'grassy', electricterrain: 'electric', psychicterrain: 'psychic', mistyterrain: 'misty' };

const out = [];
for (const [a, d, moveName, opts] of CASES) {
	for (const mode of ['doubles', 'singles']) {
		if (mode === 'singles' && (opts.spread || opts.helpingHand)) continue;
		const battle = new Battle({ formatid: FORMATS[mode], seed: [1, 2, 3, 4] });
		battle.setPlayer('p1', { team: Teams.pack([setFor(a), setFor('incin')]) });
		battle.setPlayer('p2', { team: Teams.pack([setFor(d), setFor('incin')]) });
		battle.makeChoices(mode === 'doubles' ? 'team 12' : 'team 1', mode === 'doubles' ? 'team 12' : 'team 1');
		const src = battle.p1.active[0];
		const tgt = battle.p2.active[0];
		for (const p of [src, tgt, ...battle.p1.active, ...battle.p2.active]) {
			if (p) p.clearBoosts();
		}
		battle.field.clearWeather();
		battle.field.clearTerrain();
		const weather = opts.weather || (opts.sand ? 'sandstorm' : null);
		if (weather) battle.field.setWeather(weather, src);
		if (opts.terrain) battle.field.setTerrain(opts.terrain, src);
		if (opts.atkBoost) for (const [k, v] of Object.entries(opts.atkBoost)) src.boosts[k] = v;
		if (opts.atkBoostMinus) src.boosts.atk = -opts.atkBoostMinus;
		if (opts.defBoost) for (const [k, v] of Object.entries(opts.defBoost)) tgt.boosts[k] = v;
		if (opts.helpingHand) src.addVolatile('helpinghand');
		const move = battle.dex.getActiveMove(moveName);
		if (opts.screen) battle.p2.addSideCondition(move.category === 'Physical' ? 'reflect' : 'lightscreen', tgt);
		move.willCrit = !!opts.crit || !!move.willCrit;
		if (opts.spread && mode === 'doubles') move.spreadHit = true;
		const rolls = [];
		for (let r = 0; r < 16; r++) {
			battle.random = () => r;
			// restore single-use items (resist berries are eaten by the first hit)
			tgt.item = tgt.set.item ? battle.toID(tgt.set.item) : '';
			tgt.itemState = { id: tgt.item, target: tgt };
			const m = battle.dex.getActiveMove(moveName);
			Object.assign(m, { willCrit: move.willCrit, spreadHit: move.spreadHit });
			// the type/power changes useMove() applies before damage (Weather Ball, -ate abilities)
			battle.singleEvent('ModifyType', m, null, src, tgt, m, m);
			battle.singleEvent('ModifyMove', m, null, src, tgt, m, m);
			battle.runEvent('ModifyType', src, tgt, m, m);
			battle.runEvent('ModifyMove', src, tgt, m, m);
			const dmg = battle.actions.getDamage(src, tgt, m, true);
			rolls.push(typeof dmg === 'number' ? dmg : 0);
		}
		rolls.sort((x, y) => x - y);
		out.push({
			attacker: SETS[a], defender: SETS[d], move: moveName, doubles: mode === 'doubles',
			field: {
				weather: weather ? WEATHER[weather] : null, terrain: opts.terrain ? TERRAIN[opts.terrain] : null,
				helping_hand: !!opts.helpingHand, screen: !!opts.screen, crit: !!opts.crit,
				spread: !!(opts.spread && mode === 'doubles'),
			},
			att_boosts: { ...(opts.atkBoost || {}), ...(opts.atkBoostMinus ? { atk: -opts.atkBoostMinus } : {}) },
			def_boosts: opts.defBoost || {},
			hp: tgt.maxhp, rolls,
		});
	}
}
process.stdout.write(JSON.stringify(out, null, 0) + '\n');
console.error(`${out.length} vectors`);
