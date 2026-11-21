"""
load_test.py - several visitors at once, through the main tabs, against a running app.

Each visitor opens the app with a different real tournament team (as a share link, so they can't share
cached results), then visits Analysis, Matchups (optionally pressing Find swaps), Battle plan,
Recommendations and Pokémon. Prints each step's median and worst time, the server's memory (start /
peak / end) and its CPU time. Streamlit Community Cloud gives an app up to 2 cores and throttles past
~690 MB (2.7 GB max), so run the app pinned to 2 cores and run this at low priority: the test browsers
share the machine, so their CPU slows page opens here in a way real visitors' own devices wouldn't.

    streamlit run app.py --server.headless true --server.port 8599 &
    python scripts/make_load_teams.py                    # writes data/load_test_teams.json (gitignored)
    nice -n 19 python scripts/load_test.py 10 0 swaps    # visitors, team offset, press Find swaps

Needs playwright and psutil (pip install playwright psutil; playwright install chromium).
Results (Nov 20, 2 cores): docs in the README under "Holding up under load".
"""
import asyncio, json, sys, time, threading
import psutil
from playwright.async_api import async_playwright

URL = "http://localhost:8599/"
N = int(sys.argv[1]); OFFSET = int(sys.argv[2]) if len(sys.argv) > 2 else 0
TOKENS = json.load(open(__import__("pathlib").Path(__file__).resolve().parent.parent / "data" / "load_test_teams.json"))
TABS = ["Analysis", "Matchups", "Battle plan", "Recommendations", "Pokémon"]
SWAPS = len(sys.argv) > 3 and sys.argv[3] == "swaps"

def server_procs():
    out = []
    for p in psutil.process_iter(["cmdline"]):
        if p.info["cmdline"] and "streamlit" in " ".join(p.info["cmdline"]) and "run" in p.info["cmdline"]:
            out.append(p)
    return out

peak = {"rss": 0}
stop = threading.Event()
def sampler():
    procs = server_procs()
    while not stop.is_set():
        try:
            rss = sum(p.memory_info().rss for p in procs)
            peak["rss"] = max(peak["rss"], rss)
        except psutil.Error:
            pass
        time.sleep(0.2)

async def settle(pg, limit=180):
    t0 = time.time(); await pg.wait_for_timeout(600)
    while time.time() - t0 < limit:
        busy = await pg.locator('[data-testid="stStatusWidget"]').count() + await pg.locator('[data-testid="stSkeleton"]').count()
        if not busy: break
        await pg.wait_for_timeout(250)
    return time.time() - t0

async def visitor(browser, i, results):
    ctx = await browser.new_context(viewport={"width": 390, "height": 900})
    pg = await ctx.new_page()
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    row = {"visitor": i}
    t0 = time.time()
    await pg.goto(f"{URL}?f=gen9championsvgc2026regmc&team={TOKENS[(i + OFFSET) % len(TOKENS)]}", wait_until="domcontentloaded")
    await pg.wait_for_selector('[data-testid="stTab"]', timeout=180000)
    row["open"] = await settle(pg) + (time.time() - t0) - 0  # rough
    for name in TABS:
        t = time.time()
        await pg.get_by_role("tab", name=name, exact=True).first.click()
        await settle(pg)
        row[name] = time.time() - t
        if name == "Matchups" and SWAPS:
            t = time.time()
            await pg.get_by_role("button", name="Find swaps").click(timeout=120000)
            await settle(pg, 300)
            row["Find swaps"] = time.time() - t
        if await pg.locator('[data-testid="stException"]').count():
            errors.append(f"exception on {name}")
    if await pg.get_by_text("Oh no").count():
        errors.append("Oh no page")
    row["errors"] = errors
    row["total"] = time.time() - t0
    results.append(row)
    await ctx.close()

async def main():
    th = threading.Thread(target=sampler, daemon=True); th.start()
    base = sum(p.memory_info().rss for p in server_procs())
    cpu0 = sum(sum(p.cpu_times()[:2]) for p in server_procs())
    def browser_cpu():
        t = 0.0
        for p in psutil.process_iter(["name"]):
            try:
                if p.info["name"] and ("chrom" in p.info["name"].lower() or "headless" in p.info["name"].lower()):
                    t += sum(p.cpu_times()[:2])
            except psutil.Error:
                pass
        return t
    bcpu = {"t": 0.0}
    def bsampler():
        last = {}
        while not stop.is_set():
            for p in psutil.process_iter(["name"]):
                try:
                    if p.info["name"] and ("chrom" in p.info["name"].lower() or "headless" in p.info["name"].lower()):
                        last[p.pid] = sum(p.cpu_times()[:2])
                except psutil.Error:
                    pass
            bcpu["t"] = sum(last.values())
            time.sleep(0.5)
    threading.Thread(target=bsampler, daemon=True).start()
    results = []
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        t0 = time.time()
        await asyncio.gather(*(visitor(browser, i, results) for i in range(N)))
        wall = time.time() - t0
        await browser.close()
    stop.set()
    after = sum(p.memory_info().rss for p in server_procs())
    cpu = sum(sum(p.cpu_times()[:2]) for p in server_procs()) - cpu0
    print(f"browsers CPU: {bcpu['t']:.0f} cpu-seconds total (on the same 2 cores)")
    print(f"server CPU: {cpu:.0f} cpu-seconds total, {cpu/N:.1f} per visitor, {cpu/wall:.2f} cores busy on average")
    cols = ["open"] + TABS + (["Find swaps"] if SWAPS else []) + ["total"]
    print(f"N={N}  wall {wall:.0f}s  server memory: start {base/2**20:.0f} MB, peak {peak['rss']/2**20:.0f} MB, end {after/2**20:.0f} MB")
    for c in cols:
        v = sorted(r[c] for r in results)
        print(f"  {c:16s} median {v[len(v)//2]:5.1f}s  worst {v[-1]:5.1f}s")
    errs = [e for r in results for e in r["errors"]]
    print("  errors:", errs[:5] if errs else "none")

asyncio.run(main())
