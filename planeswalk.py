#!/usr/bin/python3
import numpy as np
import pandas as pd
import argparse
import curses
import sys

# -----------------------------
# Argument parser
# -----------------------------
parser = argparse.ArgumentParser(description='Read data as of a specific date.')
parser.add_argument('--asof', type=str, required=True, help='Date in YYYY-MM-DD format')
parser.add_argument('-i', '--interactive', action='store_true',
                    help='Launch interactive curses barchart')
args = parser.parse_args()

# -----------------------------
# Pandas display options
# -----------------------------
pd.set_option('display.max_rows', None)
pd.set_option('display.max_colwidth', None)
pd.set_option('display.max_columns', None)

# -----------------------------
# Read data
# -----------------------------
df_nhis = pd.read_csv(f'sorted_NHIs_{args.asof}.csv')
df_biomes = pd.read_csv(f'sorted_biomes_{args.asof}.csv')

# Compute population per biome
df_biomes['pop'] = df_biomes.groupby('biome_id')['pid'].transform('count')

# Deduplicate biomes keeping highest blast_radius
df_biomes = df_biomes.sort_values(by='blast_radius', ascending=False)
df_biomes = df_biomes.drop_duplicates(subset='biome_id', keep='first')

# -----------------------------
# Map blast_radius to kappa
# -----------------------------
def map_blast_to_kappa(df,
                       war_col='WAR',
                       blast_col='blast_radius',
                       depth_col='depth_d',
                       sublevel_col='delta_sublevel',
                       kappa_col='kappa_equiv',
                       i_col='i_factor',
                       bigint_guardrail=23,
                       fallback_kappa_for_deep=2,
                       tol=1e-8):
    df = df.copy()
    br = df[blast_col].astype(float).copy()
    invalid_mask = br.isna() | (br <= 0) | (br > 1)
    br_nonzero = br.replace(0, np.nan)
    with np.errstate(divide='ignore', invalid='ignore'):
        delta_float = -np.log2(br_nonzero)
    sentinel = 2 * bigint_guardrail
    delta_float = delta_float.fillna(sentinel)
    delta_sublevel = np.rint(delta_float).astype(int)
    deviation = np.abs(delta_float - delta_sublevel)
    suspicious = (deviation > tol) | invalid_mask
    depth_d = (delta_sublevel // 2).astype(int)
    i_factor = np.where(delta_sublevel % 2 == 1, 1, 2)
    depth_to_kappa = {0:900,1:800,2:700,3:407,4:306,5:204,6:102,7:2}
    kappa_eq = depth_d.map(depth_to_kappa).fillna(0).astype(int)
    kappa_eq = kappa_eq.where(depth_d < bigint_guardrail, other=0)
    df[sublevel_col] = delta_sublevel
    df[depth_col] = depth_d
    df[i_col] = i_factor
    df[kappa_col] = kappa_eq
    df['mapping_suspicious'] = suspicious
    df['ctrl_max_flag'] = (df[war_col] > df[kappa_col]) & (~df['mapping_suspicious'])
    return df

df = map_blast_to_kappa(df_nhis,
                        war_col='WAR',
                        blast_col='blast_radius',
                        depth_col='depth_d',
                        sublevel_col='delta_sublevel',
                        kappa_col='kappa_equiv',
                        i_col='i_factor',
                        bigint_guardrail=23,
                        fallback_kappa_for_deep=2,
                        tol=1e-6)

# -----------------------------
# Compute combined linearized scores
# -----------------------------
min_WAR, max_WAR = df['WAR'].min(), df['WAR'].max()
df['linearized_WAR'] = ((1000 * (df['WAR'] - min_WAR) / (max_WAR - min_WAR))**2)
min_ke, max_ke = df['kappa_equiv'].min(), df['kappa_equiv'].max()
df['linearized_ke'] = ((1000 * (df['kappa_equiv'] - min_ke) / (max_ke - min_ke))**2)
df['combined'] = (df['linearized_ke'] + df['linearized_WAR']).round().astype(int)

# -----------------------------
# Counterexamples with biome info
# -----------------------------
counterexamples = df
counterexamples_summary = counterexamples[['pid','name','kappa_equiv','WAR','combined']]
counterexamples_with_biome = counterexamples_summary.merge(df_biomes[['pid','biome_id','pop']], on='pid', how='right')
counterexamples_with_biome = counterexamples_with_biome.drop(columns=['pid'])
counterexamples_with_biome = counterexamples_with_biome.reset_index(drop=True)
counterexamples_dedup = counterexamples_with_biome.groupby('biome_id', as_index=False).first()
counterexamples_dedup = counterexamples_dedup.sort_values(by=['combined','WAR','kappa_equiv','pop','biome_id'], ascending=[False,False,False,False,True])
counterexamples_dedup = counterexamples_dedup.reset_index(drop=True)
counterexamples_dedup.index = counterexamples_dedup.index + 1
counterexamples_dedup['cum_pop'] = counterexamples_dedup['pop'].cumsum()
counterexamples_dedup['percentile'] = counterexamples_dedup['combined'].rank(pct=True) * 100
counterexamples_dedup['biome_id'] = counterexamples_dedup['biome_id'].str[:12]

# -----------------------------
# Compute deciles
# -----------------------------
counterexamples_dedup['decile'] = ((counterexamples_dedup['percentile']//10).astype(int)).clip(0,9)

# -----------------------------
# Interactive curses UI
# -----------------------------
def interactive_barchart(df):
    """
    Multi-level curses UI:
      Root: decile chart (0-9)
      Decile: 10-bin histogram (percentile within decile)
      Fiber list: fibers in selected percentile bin
      ESC navigates back
    """

    # Precompute percentile bins within deciles
    df = df.copy()
    df['percentile_bin'] = (df['percentile'] % 10).astype(int)  # 0..9 within decile

    def root_screen(stdscr):
        curses.curs_set(0)
        stdscr.nodelay(False)
        decile_counts = df['decile'].value_counts().sort_index().to_dict()
        counts = [int(decile_counts.get(i,0)) for i in range(10)]
        max_count = max(counts) or 1

        while True:
            stdscr.clear()
            h,w = stdscr.getmaxyx()
            title = "Fiber Count by Decile 0-9. q=quit, 0-9 drill"
            stdscr.addstr(0,max(0,(w-len(title))//2),title)
            chart_height = h-4
            bar_width = max(3,w//20)

            for i in range(10):
                count = counts[i]
                bar_h = int((count/max_count)*chart_height)
                x = i*bar_width+2
                bar_text = "█"*(bar_width-1)
                count_label_y = h-3-bar_h
                if count_label_y>0:
                    stdscr.addstr(count_label_y,x,str(count)[:bar_width-1])
                for y in range(bar_h):
                    stdscr.addstr(h-2-y,x,bar_text)
                stdscr.addstr(h-1,x,str(i))

            stdscr.refresh()
            c = stdscr.getch()
            if c in (ord('q'), ord('Q')):
                return
            if ord('0') <= c <= ord('9'):
                decile = c - ord('0')
                percentile_screen(stdscr, decile)

    def percentile_screen(stdscr, decile):
        curses.curs_set(0)
        stdscr.nodelay(False)
        sub = df[df['decile']==decile]
        if sub.empty:
            while True:
                stdscr.clear()
                h,w = stdscr.getmaxyx()
                msg = f"Decile {decile} empty. ESC to return."
                stdscr.addstr(h//2,max(0,(w-len(msg))//2),msg)
                stdscr.refresh()
                if stdscr.getch() == 27:  # ESC
                    return

        # Histogram: count of fibers in each percentile bin (0-9)
        hist = sub['percentile_bin'].value_counts().reindex(range(10), fill_value=0).to_numpy()
        max_count = max(hist) or 1

        while True:
            stdscr.clear()
            h,w = stdscr.getmaxyx()
            title = f"Percentile histogram for decile {decile}. 0-9 drill, ESC=back"
            stdscr.addstr(0,max(0,(w-len(title))//2),title)
            chart_height = h-4
            bar_width = max(3,w//20)

            for i in range(10):
                count = hist[i]
                bar_h = int((count/max_count)*chart_height)
                x = i*bar_width+2
                bar_text = "█"*(bar_width-1)
                count_label_y = h-3-bar_h
                if count_label_y>0:
                    stdscr.addstr(count_label_y,x,str(count)[:bar_width-1])
                for y in range(bar_h):
                    stdscr.addstr(h-2-y,x,bar_text)
                stdscr.addstr(h-1,x,str(i))

            stdscr.refresh()
            c = stdscr.getch()
            if c == 27:  # ESC
                return
            if ord('0') <= c <= ord('9'):
                fiber_list_screen(stdscr, decile, c-ord('0'), sub)

    def fiber_list_screen(stdscr, decile, bin_idx, sub_df):
        curses.curs_set(0)
        stdscr.nodelay(False)

        fibers = sub_df[sub_df['percentile_bin'] == bin_idx]
        fibers_display = fibers[['name','WAR','kappa_equiv','percentile','pop']].reset_index(drop=True)
        scroll = 0

        while True:
            stdscr.clear()
            h,w = stdscr.getmaxyx()
            title = f"Fibers in decile {decile}, percentile bin {bin_idx}. ESC=back"
            stdscr.addstr(0,max(0,(w-len(title))//2),title)

            for i in range(min(h-2,len(fibers_display)-scroll)):
                row = fibers_display.iloc[i+scroll]
                line = f"{i+scroll+1:3d} {row['name'][:20]:20s} WAR:{row['WAR']:4} KE:{row['kappa_equiv']:4} PCT:{row['percentile']:5.2f} POP:{row['pop']}"
                stdscr.addstr(i+1,0,line[:w-1])

            stdscr.refresh()
            c = stdscr.getch()
            if c == 27:  # ESC
                return
            elif c == curses.KEY_DOWN and scroll < len(fibers_display)-h+2:
                scroll += 1
            elif c == curses.KEY_UP and scroll > 0:
                scroll -= 1

    curses.wrapper(root_screen)


# -----------------------------
# Launch interactive mode
# -----------------------------
if args.interactive:
    interactive_barchart(counterexamples_dedup)
    sys.exit(0)

# -----------------------------
# Print summary table if not interactive
# -----------------------------
print(counterexamples_dedup.to_string(index=True, line_width=None, justify='left'))
num_rows = counterexamples_dedup.shape[0]
num_nhis = df_biomes['pop'].sum()
print(f"Number of fibers: {num_rows}")
print(f"Number of NHIs: {num_nhis}")

