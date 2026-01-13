#!/usr/bin/python3
import numpy as np
import pandas as pd
import argparse
import curses
import sys, os

# -----------------------------
# Argument parser
# -----------------------------
parser = argparse.ArgumentParser(description='Read data as of a specific date.')
parser.add_argument('--asof', required=True, type=str, help='Date in YYYY-MM-DD format')
parser.add_argument('-i', '--interactive', action='store_true',
                    help='Launch interactive curses barchart')
args = parser.parse_args()

strict=False

# -----------------------------
# Pandas display options
# -----------------------------
pd.set_option('display.max_rows', None)
pd.set_option('display.max_colwidth', None)
pd.set_option('display.max_columns', None)

# -----------------------------
# Map blast_radius to kappa
# -----------------------------
def map_blast_to_kappa(df, blast_col='blast_radius', depth_col='depth_d',
                       sublevel_col='delta_sublevel', i_col='i_factor',
                       bigint_guardrail=23, fallback_kappa_for_deep=2, tol=1e-8):
    delta_col='kappa_equiv'
    strict_df = df.copy()
    strict_df['kappa'] = np.where(df['WAR'] >= 900, 699,
                         np.where(df['WAR'] >= 800, 588,
                         np.where(df['WAR'] >= 700, 477,
                         df['WAR'])))
    kappa_col='kappa'
    df = strict_df.copy()
    br = df[blast_col].astype(float).copy()
    br_nonzero = br.replace(0, np.nan)
    with np.errstate(divide='ignore', invalid='ignore'):
        delta_float = -np.log2(br_nonzero)
    sentinel = 2 * bigint_guardrail
    delta_float = delta_float.fillna(sentinel)
    delta_sublevel = np.rint(delta_float).astype(int)
    depth_d = (delta_sublevel // 2).astype(int)
    i_factor = np.where(delta_sublevel % 2 == 1, 1, 2)
    #depth_to_kappa = {0:900,1:800,2:700,3:407,4:306,5:204,6:102,7:2}
    depth_to_kappa = {0:699,1:588,2:477,3:366,4:244,5:122,6:2}
    kappa_eq = depth_d.map(depth_to_kappa).fillna(0).astype(int)
    kappa_eq = kappa_eq.where(depth_d < bigint_guardrail, other=0)
    df[sublevel_col] = delta_sublevel
    df[depth_col] = depth_d
    df[i_col] = i_factor
    df[delta_col] = kappa_eq
    df['ctrl_max_flag'] = (df[kappa_col] > df[delta_col])
    return df

if True:
    if os.path.exists(f'sorted_NHIs_{args.asof}.csv'):
      df_nhis = pd.read_csv(f'sorted_NHIs_{args.asof}.csv')
    else:
      print("ERR: NHI csv file not found.")
      sys.exit()
    if os.path.exists(f'fibers_{args.asof}.csv'):
      df_fibers = pd.read_csv(f'fibers_{args.asof}.csv')
      strict=True
    elif os.path.exists(f'sorted_fibers_{args.asof}.csv'):
      df_fibers = pd.read_csv(f'sorted_fibers_{args.asof}.csv')
    else:
      print("ERR: fibers csv file not found.")
      sys.exit()
    df_fibers['pop'] = df_fibers.groupby('fiber_id')['pid'].transform('count')

df = map_blast_to_kappa(df_nhis, blast_col='blast_radius', depth_col='depth_d',
                        sublevel_col='delta_sublevel', i_col='i_factor',
                        bigint_guardrail=23, fallback_kappa_for_deep=2, tol=1e-6)

# -----------------------------
# Linearize WAR and kappa
# -----------------------------
min_WAR,max_WAR = df['kappa'].min(), df['kappa'].max()
df['linearized_kappa'] = ((699*(df['kappa']-min_WAR)/(max_WAR-min_WAR))**2)
min_ke,max_ke = df['kappa_equiv'].min(), df['kappa_equiv'].max()
df['linearized_ke'] = ((699*(df['kappa_equiv']-min_ke)/(max_ke-min_ke))**2)
df['combined'] = (df['linearized_ke'] + df['linearized_kappa']).round().astype(int)

# -----------------------------
# Counterexamples and fiber info
# -----------------------------
counterexamples = df
counterexamples_summary = counterexamples[['pid','name','kappa_equiv','kappa','combined']]
counterexamples_with_fiber = counterexamples_summary.merge(df_fibers[['pid','fiber_id','pop']], on='pid', how='right')
counterexamples_with_fiber = counterexamples_with_fiber.drop(columns=['pid']).reset_index(drop=True)
# Sort to select the best representative NHI for each fiber (highest combined score)
counterexamples_with_fiber = counterexamples_with_fiber.sort_values(by=['combined','kappa','kappa_equiv'], ascending=[False,False,False])
counterexamples_dedup = counterexamples_with_fiber.groupby('fiber_id', as_index=False).first()
counterexamples_dedup['combined'] = counterexamples_dedup['combined'] + counterexamples_dedup['pop']
counterexamples_dedup = counterexamples_dedup.sort_values(by=['combined','pop','kappa','kappa_equiv','fiber_id'], ascending=[False,False,False,False,True])
counterexamples_dedup = counterexamples_dedup.reset_index(drop=True)
counterexamples_dedup.index += 1
counterexamples_dedup['cum_pop'] = counterexamples_dedup['pop'].cumsum()
counterexamples_dedup['percentile'] = counterexamples_dedup['combined'].rank(pct=True)*100
counterexamples_dedup['fiber_id'] = counterexamples_dedup['fiber_id'].str[:12]

# Deciles and percentile bins
counterexamples_dedup['decile'] = ((counterexamples_dedup['percentile']//10).astype(int)).clip(0,9)
counterexamples_dedup['percentile_bin'] = (counterexamples_dedup['percentile'] % 10).astype(int)

# -----------------------------
# Interactive curses UI
# -----------------------------
def interactive_barchart(df, df_full):
    def root_screen(stdscr):
        curses.curs_set(0)
        stdscr.nodelay(False)

        # Initialize color pairs
        curses.start_color()
        curses.use_default_colors()
        curses.init_pair(1, curses.COLOR_CYAN, -1)      # Title
        curses.init_pair(2, curses.COLOR_GREEN, -1)     # Low bars
        curses.init_pair(3, curses.COLOR_YELLOW, -1)    # Medium bars
        curses.init_pair(4, curses.COLOR_RED, -1)       # High bars
        curses.init_pair(5, curses.COLOR_WHITE, -1)     # Labels
        curses.init_pair(6, curses.COLOR_MAGENTA, -1)   # Border

        decile_counts = df['decile'].value_counts().sort_index().to_dict()
        counts = [int(decile_counts.get(i,0)) for i in range(10)]
        max_count = max(counts) or 1

        while True:
            stdscr.clear()
            h,w = stdscr.getmaxyx()

            # Draw title with border
            if strict:
              sm='(strict mode)'
            else:
              sm=''
            title = "╔══ FIBER COUNT BY DECILE "+sm+" ══╗"
            stdscr.attron(curses.color_pair(1) | curses.A_BOLD)
            stdscr.addstr(0, max(0, (w - len(title)) // 2), title)
            stdscr.attroff(curses.color_pair(1) | curses.A_BOLD)

            # Draw help text
            help_text = "Press 0-9 to drill down │ Q to quit"
            stdscr.attron(curses.color_pair(5))
            stdscr.addstr(1, max(0, (w - len(help_text)) // 2), help_text)
            stdscr.attroff(curses.color_pair(5))

            chart_height = h - 7
            bar_width = min(4, w // 15)
            spacing = max(1, bar_width // 4)
            total_width = 10 * (bar_width + spacing)
            start_x = max(2, (w - total_width) // 2)

            # Draw bars with gradient colors
            for i in range(10):
                count = counts[i]
                bar_h = int((count / max_count) * chart_height)
                x = start_x + i * (bar_width + spacing)

                # Choose color based on height
                '''
                if bar_h < chart_height * 0.33:
                    color = curses.color_pair(2)  # Green
                elif bar_h < chart_height * 0.66:
                    color = curses.color_pair(3)  # Yellow
                else:
                    color = curses.color_pair(4)  # Red
                '''
                color = curses.color_pair(2)  # Green
                # Draw count label above bar
                count_str = str(count)
                label_y = h - 4 - bar_h
                if label_y > 2:
                    stdscr.attron(curses.color_pair(5) | curses.A_BOLD)
                    stdscr.addstr(label_y, x + (bar_width - len(count_str)) // 2, count_str)
                    stdscr.attroff(curses.color_pair(5) | curses.A_BOLD)

                # Draw bar with gradient effect
                stdscr.attron(color)
                for y in range(bar_h):
                    bar_char = "█" if y < bar_h - 1 else "▀"
                    bar_text = bar_char * (bar_width - 1)
                    stdscr.addstr(h - 3 - y, x, bar_text)
                stdscr.attroff(color)

                # Draw decile label
                stdscr.attron(curses.color_pair(6) | curses.A_BOLD)
                stdscr.addstr(h - 2, x + bar_width // 2, str(i))
                stdscr.attroff(curses.color_pair(6) | curses.A_BOLD)

            # Draw axis line
            stdscr.attron(curses.color_pair(6))
            stdscr.addstr(h - 3, start_x - 1, "─" * (total_width + 2))
            stdscr.attroff(curses.color_pair(6))

            stdscr.refresh()
            c = stdscr.getch()
            if c in (ord('q'), ord('Q')):
                sys.exit(0)
            if ord('0') <= c <= ord('9'):
                percentile_screen(stdscr, c - ord('0'))

    def percentile_screen(stdscr, decile):
        curses.curs_set(0)
        stdscr.nodelay(False)

        # Color pairs already initialized in root_screen
        sub = df[df['decile']==decile]
        if sub.empty:
            while True:
                stdscr.clear()
                h,w = stdscr.getmaxyx()
                msg = f"╔══ Decile {decile} is empty ══╗"
                help_msg = "Press ESC to return │ Q to quit"
                stdscr.attron(curses.color_pair(4) | curses.A_BOLD)
                stdscr.addstr(h//2 - 1, max(0, (w - len(msg)) // 2), msg)
                stdscr.attroff(curses.color_pair(4) | curses.A_BOLD)
                stdscr.attron(curses.color_pair(5))
                stdscr.addstr(h//2 + 1, max(0, (w - len(help_msg)) // 2), help_msg)
                stdscr.attroff(curses.color_pair(5))
                stdscr.refresh()
                c = stdscr.getch()
                if c in (ord('q'), ord('Q')):
                    sys.exit(0)
                if c == 27:
                    return

        hist = sub['percentile_bin'].value_counts().reindex(range(10), fill_value=0).to_numpy()
        max_count = max(hist) or 1

        while True:
            stdscr.clear()
            h,w = stdscr.getmaxyx()

            # Draw title with border
            title = f"╔══ PERCENTILE HISTOGRAM - DECILE {decile} ══╗"
            stdscr.attron(curses.color_pair(1) | curses.A_BOLD)
            stdscr.addstr(0, max(0, (w - len(title)) // 2), title)
            stdscr.attroff(curses.color_pair(1) | curses.A_BOLD)

            # Draw help text
            help_text = "Press 0-9 for fiber list │ ESC to go back"
            stdscr.attron(curses.color_pair(5))
            stdscr.addstr(1, max(0, (w - len(help_text)) // 2), help_text)
            stdscr.attroff(curses.color_pair(5))

            chart_height = h - 7
            bar_width = min(4, w // 15)
            spacing = max(1, bar_width // 4)
            total_width = 10 * (bar_width + spacing)
            start_x = max(2, (w - total_width) // 2)

            # Draw bars with gradient colors
            for i in range(10):
                count = hist[i]
                bar_h = int((count / max_count) * chart_height)
                x = start_x + i * (bar_width + spacing)

                # Choose color based on height
                '''
                if bar_h < chart_height * 0.33:
                    color = curses.color_pair(2)  # Green
                elif bar_h < chart_height * 0.66:
                    color = curses.color_pair(3)  # Yellow
                else:
                    color = curses.color_pair(4)  # Red
                '''
                color =  curses.color_pair(2)
                # Draw count label above bar
                count_str = str(count)
                label_y = h - 4 - bar_h
                if label_y > 2:
                    stdscr.attron(curses.color_pair(5) | curses.A_BOLD)
                    stdscr.addstr(label_y, x + (bar_width - len(count_str)) // 2, count_str)
                    stdscr.attroff(curses.color_pair(5) | curses.A_BOLD)

                # Draw bar with gradient effect
                stdscr.attron(color)
                for y in range(bar_h):
                    bar_char = "█" if y < bar_h - 1 else "▀"
                    bar_text = bar_char * (bar_width - 1)
                    stdscr.addstr(h - 3 - y, x, bar_text)
                stdscr.attroff(color)

                # Draw percentile bin label with range
                percentile_range = f"{decile}{i}"
                stdscr.attron(curses.color_pair(6) | curses.A_BOLD)
                stdscr.addstr(h - 2, x + (bar_width - len(percentile_range)) // 2, percentile_range)
                stdscr.attroff(curses.color_pair(6) | curses.A_BOLD)

            # Draw axis line
            stdscr.attron(curses.color_pair(6))
            stdscr.addstr(h - 3, start_x - 1, "─" * (total_width + 2))
            stdscr.attroff(curses.color_pair(6))

            stdscr.refresh()
            c = stdscr.getch()
            if c in (ord('q'), ord('Q')):
                sys.exit(0)
            if c == 27:
                return
            if ord('0') <= c <= ord('9'):
                fiber_list_screen(stdscr, decile, c-ord('0'), sub)

    def fiber_list_screen(stdscr, decile, bin_idx, sub_df):
        curses.curs_set(0)
        stdscr.nodelay(False)
        fibers = sub_df[sub_df['percentile_bin']==bin_idx]
        fibers_display = fibers[['fiber_id','kappa','kappa_equiv','percentile','pop']].reset_index(drop=True)
        scroll = 0
        selected_index = 0  # Track which fiber is selected

        while True:
            stdscr.clear()
            h,w = stdscr.getmaxyx()

            # Draw title
            title = f"╔══ FIBERS: DECILE {decile}, PERCENTILE {decile}{bin_idx} ══╗"
            stdscr.attron(curses.color_pair(1) | curses.A_BOLD)
            stdscr.addstr(0, max(0, (w - len(title)) // 2), title)
            stdscr.attroff(curses.color_pair(1) | curses.A_BOLD)

            # Draw help text
            help_text = "↑↓ to select │ SPACE for NHI details │ ESC to go back │ Q to quit"
            stdscr.attron(curses.color_pair(5))
            stdscr.addstr(1, max(0, (w - len(help_text)) // 2), help_text)
            stdscr.attroff(curses.color_pair(5))

            # Draw header
            header = "  # FIBER_ID      REPRESENTATIVE NHI                                               KAPPA  DELTA  PERCENTILE POP"
            stdscr.attron(curses.color_pair(6) | curses.A_BOLD)
            stdscr.addstr(2, 2, header[:w-4])
            stdscr.addstr(3, 2, "─" * min(len(header), w-4))
            stdscr.attroff(curses.color_pair(6) | curses.A_BOLD)

            # Draw fibers with alternating colors
            visible_rows = min(h - 5, len(fibers_display) - scroll)
            for i in range(visible_rows):
                absolute_index = i + scroll
                row = fibers_display.iloc[absolute_index]
                current_fiber_id_truncated = fibers_display.iloc[absolute_index]['fiber_id']
                current_fiber_nhis = df_full[df_full['fiber_id'].str.startswith(current_fiber_id_truncated)]
                first_nhi_name = current_fiber_nhis['name'].iloc[0] if not current_fiber_nhis.empty else "N/A"
                line = f"{absolute_index+1:3d} {row['fiber_id'][:13]:13s} {first_nhi_name[:64]:64} {row['kappa']:3}    {row['kappa_equiv']:3}   {row['percentile']:6.2f}  {row['pop']:5}"

                # Determine if this is the selected row
                is_selected = (absolute_index == selected_index)

                if is_selected:
                    # Highlight selected row with reverse video
                    stdscr.attron(curses.color_pair(5) | curses.A_REVERSE)
                elif i % 2 == 0:
                    stdscr.attron(curses.color_pair(5))
                else:
                    stdscr.attron(curses.color_pair(5) | curses.A_DIM)

                stdscr.addstr(i + 4, 2, line[:w-4])

                if is_selected:
                    stdscr.attroff(curses.color_pair(5) | curses.A_REVERSE)
                else:
                    stdscr.attroff(curses.color_pair(5) | curses.A_DIM)

            # Draw scroll indicator
            if len(fibers_display) > visible_rows:
                scroll_info = f"[{scroll+1}-{scroll+visible_rows} of {len(fibers_display)}]"
                stdscr.attron(curses.color_pair(6))
                stdscr.addstr(h - 1, w - len(scroll_info) - 2, scroll_info)
                stdscr.attroff(curses.color_pair(6))

            stdscr.refresh()
            c = stdscr.getch()

            if c in (ord('q'), ord('Q')):
                sys.exit(0)
            elif c == 27:  # ESC
                return
            elif c == ord(' '):  # SPACE
                # Get the selected fiber's fiber_id (need to reconstruct the full ID)
                selected_fiber_id = fibers_display.iloc[selected_index]['fiber_id']
                nhi_detail_screen(stdscr, selected_fiber_id, decile, bin_idx)
            elif c == curses.KEY_DOWN:
                if selected_index < len(fibers_display) - 1:
                    selected_index += 1
                    # Auto-scroll if selection goes below visible area
                    if selected_index >= scroll + visible_rows:
                        scroll = selected_index - visible_rows + 1
            elif c == curses.KEY_UP:
                if selected_index > 0:
                    selected_index -= 1
                    # Auto-scroll if selection goes above visible area
                    if selected_index < scroll:
                        scroll = selected_index

    def nhi_detail_screen(stdscr, fiber_id_truncated, decile, bin_idx):
        """Display all NHIs belonging to a specific fiber."""
        curses.curs_set(0)
        stdscr.nodelay(False)

        # Find all NHIs in this fiber (fiber_id is truncated in display, so match by prefix)
        fiber_nhis = df_full[df_full['fiber_id'].str.startswith(fiber_id_truncated)]

        if fiber_nhis.empty:
            while True:
                stdscr.clear()
                h, w = stdscr.getmaxyx()
                msg = f"╔══ No NHIs found for fiber {fiber_id_truncated} ══╗"
                help_msg = "Press ESC to return │ Q to quit"
                stdscr.attron(curses.color_pair(4) | curses.A_BOLD)
                stdscr.addstr(h//2 - 1, max(0, (w - len(msg)) // 2), msg)
                stdscr.attroff(curses.color_pair(4) | curses.A_BOLD)
                stdscr.attron(curses.color_pair(5))
                stdscr.addstr(h//2 + 1, max(0, (w - len(help_msg)) // 2), help_msg)
                stdscr.attroff(curses.color_pair(5))
                stdscr.refresh()
                c = stdscr.getch()
                if c in (ord('q'), ord('Q')):
                    sys.exit(0)
                if c == 27:
                    return

        nhis_display = fiber_nhis[['name', 'kappa', 'kappa_equiv', 'combined']].reset_index(drop=True)
        scroll = 0

        while True:
            stdscr.clear()
            h, w = stdscr.getmaxyx()

            # Draw title
            title = f"╔══ NHIs IN FIBER {fiber_id_truncated} ══╗"
            stdscr.attron(curses.color_pair(1) | curses.A_BOLD)
            stdscr.addstr(0, max(0, (w - len(title)) // 2), title)
            stdscr.attroff(curses.color_pair(1) | curses.A_BOLD)

            # Draw help text
            help_text = "↑↓ to scroll │ ESC to go back │ Q to quit"
            stdscr.attron(curses.color_pair(5))
            stdscr.addstr(1, max(0, (w - len(help_text)) // 2), help_text)
            stdscr.attroff(curses.color_pair(5))

            # Draw header
            header = "  # NHI NAME                                                          KAPPA  DELTA  "
            stdscr.attron(curses.color_pair(6) | curses.A_BOLD)
            stdscr.addstr(2, 2, header[:w-4])
            stdscr.addstr(3, 2, "─" * min(len(header), w-4))
            stdscr.attroff(curses.color_pair(6) | curses.A_BOLD)

            # Draw NHIs with alternating colors
            visible_rows = min(h - 5, len(nhis_display) - scroll)
            for i in range(visible_rows):
                row = nhis_display.iloc[i + scroll]
                line = f"{i+scroll+1:3d} {row['name'][:64]:64s} {row['kappa']:4}   {row['kappa_equiv']:4}  "

                # Alternate row colors for readability
                if i % 2 == 0:
                    stdscr.attron(curses.color_pair(5))
                else:
                    stdscr.attron(curses.color_pair(5) | curses.A_DIM)

                stdscr.addstr(i + 4, 2, line[:w-4])
                stdscr.attroff(curses.color_pair(5) | curses.A_DIM)

            # Draw scroll indicator
            if len(nhis_display) > visible_rows:
                scroll_info = f"[{scroll+1}-{scroll+visible_rows} of {len(nhis_display)}]"
                stdscr.attron(curses.color_pair(6))
                stdscr.addstr(h - 1, w - len(scroll_info) - 2, scroll_info)
                stdscr.attroff(curses.color_pair(6))

            # Show total count
            count_info = f"Total NHIs: {len(nhis_display)}"
            stdscr.attron(curses.color_pair(6))
            stdscr.addstr(h - 1, 2, count_info)
            stdscr.attroff(curses.color_pair(6))

            stdscr.refresh()
            c = stdscr.getch()

            if c in (ord('q'), ord('Q')):
                sys.exit(0)
            elif c == 27:  # ESC
                return
            elif c == curses.KEY_DOWN and scroll < len(nhis_display) - visible_rows:
                scroll += 1
            elif c == curses.KEY_UP and scroll > 0:
                scroll -= 1

    curses.wrapper(root_screen)

# -----------------------------
# Launch interactive mode
# -----------------------------
if args.interactive:
    interactive_barchart(counterexamples_dedup, counterexamples_with_fiber)
    sys.exit(0)

# -----------------------------
# Print summary table if not interactive
# -----------------------------
counterexamples_dedup=counterexamples_dedup.drop(columns=["decile","percentile_bin","combined"])
counterexamples_dedup=counterexamples_dedup.rename(columns={'name':'NHI representative','kappa_equiv':'delta'})
print(counterexamples_dedup.to_string(index=True, line_width=None, justify='left'))
num_rows = counterexamples_dedup.shape[0]
num_nhis = counterexamples_dedup['cum_pop'].iloc[-1]
print(f"Number of fibers: {num_rows}")
print(f"Number of NHIs: {num_nhis}")

