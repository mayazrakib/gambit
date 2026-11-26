export const WORKSPACE_TEMPLATE = `
    <main class="workspace">
        <header class="page_header">
            <h1>Gambit</h1>
            <button id="theme_toggle" class="theme_toggle" type="button" aria-label="Switch to dark mode" title="Switch to dark mode"></button>
        </header>
        <div id="error_banner" class="error_banner" role="alert" hidden><span id="error_text"></span><button id="dismiss_error" aria-label="Dismiss error">×</button></div>
        <div class="workspace_grid">
            <section class="board_panel" aria-label="Chess game">
                <div class="player_row"><h2>Stockfish</h2><span id="opponent_summary">Not configured</span><button id="retry_opponent" class="text_button" hidden>Retry reply</button><span id="engine_status" class="turn_badge">Idle</span></div>
                <div class="board_surface"><chess-board aria-label="Playing board"></chess-board><div id="board_empty" class="board_empty"><p>No active game.</p><button id="start_first" class="button primary">New game</button></div></div>
                <div class="player_row learner_row"><h2>You</h2><span id="player_color">White</span><span id="position_status" role="status">No active game.</span><span id="player_status" class="turn_badge" hidden>Your turn</span></div>
                <div class="board_toolbar"><div class="button_row"><button id="undo" class="button secondary" aria-label="Take back your last turn" disabled>Undo</button><button id="flip" class="button secondary" title="Flip board (F)" aria-keyshortcuts="f">Flip</button><button id="clear" class="button secondary" aria-label="Clear tutor annotations" disabled>Clear marks</button></div><button id="claim_draw" class="button secondary" disabled>Claim draw</button><button id="export" class="button secondary" disabled>Export PGN</button></div>
                <div class="position_data"><span id="move_counter">No moves</span><code id="position_fen"></code></div>
            </section>
            <aside class="sidebar" aria-label="Game controls">
                <div class="control_heading"><h2>Game controls</h2></div><p class="field_note">Temporary game. Server restart clears the board and analysis.</p>
                <div class="game_controls">
                    <button id="new_game" class="button primary">New game</button>
                    <div class="connection"><span id="connection_dot" class="status_dot"></span><span id="connection_text" role="status">Connecting</span></div>
                </div>
                <section class="card tutor_card"><div class="card_heading"><h2>Evidence</h2><label class="profile_label">Search<select id="analysis_profile" aria-label="Teaching analysis budget"><option value="instant">Instant</option><option value="quick">Quick</option><option value="deep">Deep</option></select></label></div><div class="tutor_actions"><button id="hint" title="Hint (H)" aria-keyshortcuts="h" class="button secondary" disabled>Hint</button><button id="explain" class="button secondary" disabled>Analyze position</button><button id="cancel_teaching" class="button secondary" hidden>Cancel</button></div><label class="switch_label"><input id="auto_coach" type="checkbox">Analyze after engine reply</label><div class="tutor_message" aria-live="polite" aria-atomic="true"><span class="message_label" id="teaching_label">Idle</span><p id="teaching_message">No analysis.</p><span id="teaching_metrics" class="teaching_metrics"></span></div></section>
                <section class="card moves_card"><div class="card_heading"><h2>Moves</h2><span id="history_count" class="count_badge">0 plies</span></div><div class="moves_header"><span>#</span><span>White</span><span>Black</span></div><div id="move_list" class="move_list" tabindex="0" aria-label="Move history"><p class="empty_history">No moves.</p></div></section>
                <section class="connection_panel"><details><summary>MCP / Voice</summary><p>Use the existing Gambit connection in ChatGPT Live. The UI and MCP server must share the same database.</p><code id="mcp_address"></code></details></section>
            </aside>
        </div>
    </main>
    <dialog id="setup_dialog" aria-labelledby="setup_title"><form id="setup_form"><div class="dialog_heading"><h2 id="setup_title">New game</h2><button type="button" id="close_setup" class="icon_button" aria-label="Close game setup">×</button></div>
        <fieldset class="side_choices"><legend>Player</legend><label><input type="radio" name="player_color" value="white" checked>White</label><label><input type="radio" name="player_color" value="black">Black</label></fieldset>
        <div class="form_grid"><label>Strength mode<select name="strength_mode" id="strength_mode"><option value="skill">Skill level</option><option value="elo">Target Elo</option><option value="full">Full strength</option></select></label><label id="skill_field">Skill level <span id="skill_value">8 / 20</span><input type="range" name="skill_level" id="skill_level" min="0" max="20" value="8"></label><label id="elo_field" hidden>Target Elo<input type="number" name="target_elo" value="1500" step="1" min="100" max="4000"><span class="field_note">Engine target; not a platform rating.</span></label></div>
        <div class="form_grid"><label>Search limit<select name="budget_mode" id="budget_mode"><option value="time">Time</option><option value="depth">Depth</option><option value="nodes">Nodes</option></select></label><label>Time cap / move<select name="think_time_ms"><option value="150">150 ms</option><option value="500" selected>500 ms</option><option value="1000">1,000 ms</option><option value="3000">3,000 ms</option><option value="5000">5,000 ms</option></select></label><label id="depth_field" hidden>Depth<input name="depth" type="number" min="1" max="24" value="12"></label><label id="nodes_field" hidden>Nodes<input name="nodes" type="number" min="100" max="2000000" value="100000" step="100"></label></div>
        <details class="advanced_settings"><summary>Engine / position</summary><div class="form_grid"><label>Threads<input name="threads" type="number" min="1" max="8" value="1"></label><label>Hash (MiB)<input name="hash_mb" type="number" min="16" max="512" value="32"></label></div><label>Starting FEN<textarea id="root_fen" rows="2" spellcheck="false" placeholder="Standard starting position"></textarea></label></details>
        <p class="field_note" id="setup_note">Opponent settings are independent of tutor analysis.</p><p id="setup_error" class="setup_error" role="alert"></p><div class="dialog_actions"><button type="button" id="cancel_setup" class="button secondary">Cancel</button><button type="submit" id="start_game" class="button primary">Start game</button></div>
    </form></dialog>
`;
