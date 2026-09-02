import streamlit as st
import folium
from streamlit_folium import st_folium
import numpy as np
import pandas as pd
import os
import qrcode
from io import BytesIO

st.set_page_config(page_title="Accent GeoGuessr", layout="wide")

if not os.path.exists("clips"):
    os.makedirs("clips")

# Set your secret teacher passcode here
TEACHER_PASSWORD = "0712"

# Automatically construct the public web URL for the QR code
host_url = st.context.headers.get("host", "localhost:8501")
STUDENT_JOIN_URL = f"https://{host_url}"

def generate_qr_code(url):
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=2,
    )
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()

# ==========================================
# 1. SHARED GLOBAL STORE (Cross-Tab Sync)
# ==========================================
@st.cache_resource
def get_global_store():
    return {
        "playlist": [],          # [{round_num, clip_path, timer, lat, lon}]
        "all_guesses": pd.DataFrame(columns=['round_num', 'name', 'lat', 'lon']),
        "joined_students": set(),# Tracks students who signed in during lobby phase
        "active_round_idx": -1,  # -1 = Lobby / Waiting Room, 0+ = Active Rounds
        "show_leaderboard": False,
        "show_grand_finale": False,
        "game_started": False,
        "lobby_locked": False,   # NEW: Locks new joins once Round 1 starts
        "game_id": 1             # Cache buster for resets
    }

store = get_global_store()

def create_bounded_map(location=[20.0, 0.0], zoom_start=1):
    m = folium.Map(location=location, zoom_start=zoom_start, tiles=None)
    folium.TileLayer('OpenStreetMap', no_wrap=True).add_to(m)
    return m

# ==========================================
# 2. HAVERSINE PHYSICS SCORING ENGINE
# ==========================================
def calculate_scores(guesses_df, target_lat, target_lon):
    if guesses_df.empty:
        return guesses_df
        
    R = 6371.0  # Earth radius in km
    lats = guesses_df['lat'].astype(float).values
    lons = guesses_df['lon'].astype(float).values
    
    lat1, lon1 = np.radians(float(target_lat)), np.radians(float(target_lon))
    lat2 = np.radians(lats)
    lon2 = np.radians(lons)
    
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    
    a = np.sin(dlat/2)**2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon/2)**2
    c = 2 * np.arcsin(np.sqrt(a))
    distances = R * c
    
    # Subtracts 0.5 pts per km (reaches 0 at 10,000 km)
    scores = np.clip(5000 - (distances * 0.5), 0, 5000).astype(int)
    guesses_df['distance_km'] = np.round(distances, 1)
    guesses_df['score'] = scores
    return guesses_df.sort_values(by='score', ascending=False)

def calculate_total_scores(playlist, all_guesses):
    if all_guesses.empty or not playlist:
        return pd.DataFrame(columns=['name', 'total_score', 'rounds_played'])

    all_round_results = []
    for r in playlist:
        r_num = r['round_num']
        r_guesses = all_guesses[all_guesses['round_num'] == r_num]
        if not r_guesses.empty:
            scored_df = calculate_scores(r_guesses.copy(), r['lat'], r['lon'])
            all_round_results.append(scored_df)
            
    if not all_round_results:
        return pd.DataFrame(columns=['name', 'total_score', 'rounds_played'])

    combined_df = pd.concat(all_round_results, ignore_index=True)
    
    total_df = combined_df.groupby('name').agg(
        total_score=('score', 'sum'),
        rounds_played=('round_num', 'count')
    ).reset_index()

    return total_df.sort_values(by='total_score', ascending=False)

def reset_game_data(keep_playlist=True):
    store["all_guesses"] = pd.DataFrame(columns=['round_num', 'name', 'lat', 'lon'])
    store["joined_students"] = set()
    store["active_round_idx"] = -1
    store["show_leaderboard"] = False
    store["show_grand_finale"] = False
    store["game_started"] = False
    store["lobby_locked"] = False
    store["game_id"] += 1
    if not keep_playlist:
        store["playlist"] = []
    st.session_state.clear()

params = st.query_params

# ==========================================
# 3. FRAGMENTS FOR DYNAMIC AUTO-REFRESHING
# ==========================================
@st.fragment(run_every=2)
def poll_teacher_lobby():
    st.metric(label="Players Connected", value=len(store["joined_students"]))
    if store["joined_students"]:
        st.write("**Joined Players:**")
        st.write(", ".join(sorted(store["joined_students"])))
    else:
        st.info("Waiting for the first student to enter their name...")

@st.fragment(run_every=2)
def poll_teacher_guess_counter(curr_idx):
    round_guesses = store["all_guesses"][
        store["all_guesses"]['round_num'] == (curr_idx + 1)
    ]
    st.metric(label="Student Guesses Received 📥", value=len(round_guesses))

@st.fragment(run_every=2)
def poll_student_waiting_state():
    if not store["playlist"]:
        st.info("Waiting for the teacher to set up game rounds...")
    elif not store["game_started"]:
        st.info("⏳ Waiting for the teacher to open the lobby...")
        st.session_state.my_name = ""
    elif store["game_started"] and st.session_state.get("my_name"):
        if store["active_round_idx"] == -1:
            st.success(f"👋 Welcome, **{st.session_state.my_name}**!")
            st.info("🎮 You're in! Watch the projector screen—the teacher will begin Round 1 shortly.")
        else:
            st.rerun()
    else:
        st.rerun()

# ==========================================
# 4. TEACHER VIEW (?role=teacher)
# ==========================================
if params.get("role") == "teacher":
    
    # PASSCODE GATEKEEPER
    if "teacher_authenticated" not in st.session_state:
        st.session_state.teacher_authenticated = False
        
    if not st.session_state.teacher_authenticated:
        st.title("🔒 Teacher Access Required")
        pass_input = st.text_input("Enter Passcode:", type="password")
        if st.button("Unlock Panel"):
            if pass_input == TEACHER_PASSWORD:
                st.session_state.teacher_authenticated = True
                st.rerun()
            else:
                st.error("Incorrect passcode!")
        st.stop()
        
    st.title("🎯 Accent GeoGuessr — Teacher Panel")
    
    tab1, tab2 = st.tabs(["📝 Pre-Class Setup", "📺 Live Projector Screen"])
    
    # TAB 1: PRE-CLASS SETUP
    with tab1:
        st.subheader("1. Add Media & Create Playlist")
        
        with st.expander("Upload New Media Clip (Backup Method for Online Hosting)", expanded=True):
            uploaded_file = st.file_uploader(
                "Drag & drop an audio or video clip from your laptop:",
                type=["mp3", "mp4", "wav", "m4a"]
            )
            if uploaded_file is not None:
                save_path = os.path.join("clips", uploaded_file.name)
                with open(save_path, "wb") as f:
                    f.write(uploaded_file.getbuffer())
                st.success(f"✅ Saved `{uploaded_file.name}` to server! You can now select it below.")
        
        st.markdown("---")
        
        available_clips = [f for f in os.listdir("clips") if f.endswith(('.mp4', '.mp3', '.m4a', '.wav'))]
        
        col_setup1, col_setup2 = st.columns([3, 2])
        
        with col_setup1:
            st.write("Click on the map to set the actual origin of the accent:")
            m_setup = create_bounded_map(location=[20.0, 0.0], zoom_start=1)

            if "temp_lat" not in st.session_state:
                st.session_state.temp_lat = None
                st.session_state.temp_lon = None

            if st.session_state.temp_lat is not None:
                folium.Marker(
                    [st.session_state.temp_lat, st.session_state.temp_lon],
                    popup="Current Target",
                    icon=folium.Icon(color='green', icon='star')
                ).add_to(m_setup)

            setup_map_data = st_folium(m_setup, height=350, width=None, key=f"setup_map_g{store['game_id']}")

            if setup_map_data and setup_map_data.get("last_clicked"):
                clat = setup_map_data["last_clicked"]["lat"]
                clon = setup_map_data["last_clicked"]["lng"]
                if clat != st.session_state.temp_lat or clon != st.session_state.temp_lon:
                    st.session_state.temp_lat = clat
                    st.session_state.temp_lon = clon
                    st.rerun()

        with col_setup2:
            if st.session_state.temp_lat is not None:
                st.success("🎯 Target Pin Selected on Map!")

            with st.form(key="add_round_form", clear_on_submit=True):
                if available_clips:
                    selected_clip = st.selectbox("Select Clip File:", available_clips)
                else:
                    st.warning("No clips available. Upload a file above or push clips to GitHub.")
                    selected_clip = None
                    
                timer_seconds = st.number_input("Set Round Timer (seconds):", min_value=10, max_value=300, value=45, step=5)
                submit_button = st.form_submit_button("➕ Save Round to Playlist")

            if submit_button:
                if selected_clip and st.session_state.temp_lat is not None:
                    new_round = {
                        "round_num": len(store["playlist"]) + 1,
                        "clip_path": f"clips/{selected_clip}",
                        "timer": timer_seconds,
                        "lat": st.session_state.temp_lat,
                        "lon": st.session_state.temp_lon
                    }
                    store["playlist"].append(new_round)
                    st.session_state.temp_lat = None
                    st.session_state.temp_lon = None
                    st.success(f"✅ Round {len(store['playlist'])} saved!")
                    st.rerun()
                else:
                    st.error("⚠️ Please select a map pin AND a media clip file!")

            st.markdown("---")
            st.subheader("⚙️ Game Control & Reset")
            
            col_res1, col_res2 = st.columns(2)
            with col_res1:
                if st.button("🔄 Reset Scores (Keep Playlist)"):
                    reset_game_data(keep_playlist=True)
                    st.success("Game reset! Playlist kept, scores cleared.")
                    st.rerun()

            with col_res2:
                if st.button("🗑️ Delete Everything & Reset"):
                    reset_game_data(keep_playlist=False)
                    st.warning("All game data and playlist wiped clean.")
                    st.rerun()

        st.markdown("---")
        st.subheader("🗺️ Playlist Overview Map")
        if store["playlist"]:
            map_col, _ = st.columns([3, 2])
            with map_col:
                m_overview = create_bounded_map(location=[20.0, 0.0], zoom_start=1)
                for r in store["playlist"]:
                    folium.Marker(
                        [r['lat'], r['lon']],
                        popup=f"Round {r['round_num']}",
                        icon=folium.Icon(color='blue', icon='info-sign')
                    ).add_to(m_overview)
                st_folium(m_overview, height=350, width=None, key=f"overview_map_g{store['game_id']}")

    # TAB 2: LIVE PROJECTOR SCREEN
    with tab2:
        if not store["playlist"]:
            st.warning("No rounds created yet! Add rounds in the 'Pre-Class Setup' tab first.")
        else:
            if not store["game_started"]:
                st.info("Game is not started yet.")
                if st.button("OPEN STUDENT LOBBY", type="primary"):
                    store["game_started"] = True
                    store["active_round_idx"] = -1
                    st.rerun()

            # LOBBY / WAITING ROOM SCREEN WITH AUTOMATIC QR CODE
            elif store["active_round_idx"] == -1:
                st.header("Welcome to Accent GeoGuessr!")
                #st.subheader("Scan the QR Code or type the URL on your device to join!")
                
                col_qr, col_lobby1, col_lobby2 = st.columns([1, 1, 1])
                
                with col_qr:
                    st.markdown("### 📷 Scan to Join")
                    qr_img_bytes = generate_qr_code(STUDENT_JOIN_URL)
                    st.image(qr_img_bytes, width=220)
                    st.caption(f"URL: `{STUDENT_JOIN_URL}`")

                with col_lobby1:
                    st.markdown("### 👥 Players")
                    poll_teacher_lobby()

                with col_lobby2:
                    st.markdown("### Controls")
                    if st.button("Begin Round 1!", type="primary", use_container_width=True):
                        store["active_round_idx"] = 0
                        store["lobby_locked"] = True  # Locks out late joins
                        st.rerun()

            # ACTIVE GAMEPLAY & RESULTS
            else:
                curr_idx = store["active_round_idx"]
                total_rounds = len(store["playlist"])
                is_last_round = (curr_idx == total_rounds - 1)
                
                # SCREEN MODE A: GRAND FINALE PODIUM
                if store["show_grand_finale"]:
                    st.header("🏆 FINAL SCOREBOARD 🏆")
                    
                    totals_df = calculate_total_scores(store["playlist"], store["all_guesses"])
                    
                    if totals_df.empty:
                        st.info("No student scores were submitted during this game.")
                    else:
                        top_students = totals_df.head(3).to_dict('records')
                        medals = ["🥇 1st Place", "🥈 2nd Place", "🥉 3rd Place"]
                        
                        cols = st.columns(len(top_students))
                        for i, student in enumerate(top_students):
                            with cols[i]:
                                st.metric(
                                    label=medals[i],
                                    value=f"{student['name']}",
                                    delta=f"{student['total_score']} pts"
                                )
                        
                        st.markdown("---")
                        st.subheader("📊 Final Overall Game Leaderboard")
                        totals_df_display = totals_df.rename(columns={
                            'name': 'Student',
                            'total_score': 'Total Points',
                            'rounds_played': 'Rounds Played'
                        })
                        st.dataframe(totals_df_display, use_container_width=True, hide_index=True)

                        # --- CLASS COMPARISON STATS ---
                        st.markdown("---")
                        st.subheader("📈 Class Overall Benchmark")
                        
                        avg_class_score = int(round(totals_df['total_score'].mean()))
                        total_players = len(totals_df)
                        avg_per_round = int(round(avg_class_score / total_rounds)) if total_rounds > 0 else 0
                        
                        m_col1, m_col2, m_col3 = st.columns(3)
                        with m_col1:
                            st.metric("🎓 Class Average Total Score", f"{avg_class_score:,} pts")
                        with m_col2:
                            st.metric("🎯 Avg Points / Player / Round", f"{avg_per_round:,} pts")
                        with m_col3:
                            st.metric("👥 Total Class Participants", f"{total_players} players")

                    st.markdown("---")
                    if st.button("🔄 Play Again (Reset Scores)", type="primary"):
                        reset_game_data(keep_playlist=True)
                        store["game_started"] = True
                        st.rerun()

                # SCREEN MODE B: DEDICATED ROUND RESULTS SCREEN
                elif store["show_leaderboard"]:
                    curr_round = store["playlist"][curr_idx]
                    round_guesses = store["all_guesses"][
                        store["all_guesses"]['round_num'] == (curr_idx + 1)
                    ]
                    
                    st.header(f"📊 Round {curr_idx + 1} Results")
                    
                    res_col1, res_col2 = st.columns([3, 2])
                    
                    results = pd.DataFrame()
                    if not round_guesses.empty:
                        results = calculate_scores(round_guesses.copy(), curr_round["lat"], curr_round["lon"])

                    with res_col1:
                        if round_guesses.empty:
                            st.info("No student guesses received for this round.")
                        else:
                            res_map = create_bounded_map(location=[curr_round["lat"], curr_round["lon"]], zoom_start=1)
                            bounds = [[curr_round["lat"], curr_round["lon"]]]
                            
                            folium.Marker(
                                [curr_round["lat"], curr_round["lon"]], 
                                popup="Target Origin", 
                                icon=folium.Icon(color='green', icon='star')
                            ).add_to(res_map)
                            
                            for _, row in results.iterrows():
                                lat_val, lon_val = float(row['lat']), float(row['lon'])
                                bounds.append([lat_val, lon_val])
                                folium.Marker(
                                    [lat_val, lon_val], 
                                    popup=f"{row['name']}: {row['score']} pts"
                                ).add_to(res_map)
                            
                            if len(bounds) > 1:
                                res_map.fit_bounds(bounds, padding=[30, 30])
                            
                            st_folium(res_map, height=450, width=None, key=f"res_map_g{store['game_id']}_r{curr_idx}")

                    with res_col2:
                        st.subheader(f"⚡ Top 5 — Round {curr_idx + 1}")
                        
                        if results.empty:
                            st.info("No student scores for this round.")
                        else:
                            top_5_round = results.head(5)[['name', 'distance_km', 'score']].rename(columns={
                                'name': 'Student',
                                'distance_km': 'Distance (km)',
                                'score': 'Round Points'
                            })
                            st.dataframe(top_5_round, use_container_width=True, hide_index=True)

                            # --- ROUND AVERAGE STAT ---
                            round_avg = int(round(results['score'].mean()))
                            st.caption(f"📊 **Class Round Average:** {round_avg:,} pts")

                        if not is_last_round:
                            st.markdown("---")
                            st.subheader("🔥 Top 3 Overall Leaders")
                            totals_df = calculate_total_scores(store["playlist"], store["all_guesses"])
                            
                            if totals_df.empty:
                                st.info("No overall standings yet.")
                            else:
                                top_3_global = totals_df.head(3)[['name', 'total_score']].rename(columns={
                                    'name': 'Student',
                                    'total_score': 'Total Points'
                                })
                                st.dataframe(top_3_global, use_container_width=True, hide_index=True)

                        st.markdown("---")
                        if not is_last_round:
                            if st.button("Next Round ➡️", type="primary", use_container_width=True):
                                store["active_round_idx"] += 1
                                store["show_leaderboard"] = False
                                st.rerun()
                        else:
                            if st.button("🏆 Show Final Scores!", type="primary", use_container_width=True):
                                store["show_grand_finale"] = True
                                st.rerun()

                # SCREEN MODE C: ACTIVE GAMEPLAY
                else:
                    curr_round = store["playlist"][curr_idx]
                    st.header(f"🔊 Round {curr_idx + 1} of {total_rounds}")
                    
                    col_left, col_right = st.columns([3, 2])
                    
                    with col_left:
                        if curr_round["clip_path"].endswith(('.mp3', '.m4a', '.wav')):
                            st.audio(curr_round["clip_path"])
                        else:
                            st.video(curr_round["clip_path"])
                    
                    with col_right:
                        poll_teacher_guess_counter(curr_idx)
                        
                        if st.button("🏆 Lock & Reveal Map Results", type="primary", use_container_width=True):
                            store["show_leaderboard"] = True
                            st.rerun()

# ==========================================
# 5. STUDENT VIEW (Default URL)
# ==========================================
else:
    st.title("📱 Student Controller")
    
    if "my_name" not in st.session_state:
        st.session_state.my_name = ""
        
    if not store["playlist"] or not store["game_started"]:
        poll_student_waiting_state()
    else:
        # CHECK IF LOBBY IS LOCKED FOR NEW UNREGISTERED PLAYERS
        if store["lobby_locked"] and not st.session_state.my_name:
            st.error("🔒 Game in Progress")
            st.warning("The lobby is locked because Round 1 has already started. Wait for the teacher to start a new game!")
        
        # STUDENT ENTRY FORM (LOBBY OPEN)
        elif not st.session_state.my_name:
            st.subheader("Join the Game")
            nickname_input = st.text_input("Enter your Nickname:", placeholder="e.g. Alex")
            if st.button("Start Playing ➡️"):
                if nickname_input.strip():
                    name = nickname_input.strip()
                    st.session_state.my_name = name
                    store["joined_students"].add(name)
                    st.rerun()
                else:
                    st.error("Please enter a nickname first!")
        
        # WAITING IN LOBBY
        elif store["active_round_idx"] == -1:
            poll_student_waiting_state()

        # ACTIVE ROUND GAMEPLAY
        else:
            curr_idx = store["active_round_idx"]
            curr_round_num = curr_idx + 1
            
            lock_key = f"submitted_g{store['game_id']}_r{curr_round_num}"
            if lock_key not in st.session_state:
                st.session_state[lock_key] = False

            if st.session_state[lock_key]:
                st.success(f"🔒 Round {curr_round_num} Guess Locked In!")
                st.info("Look at the main projector screen for round results.")
                
                @st.fragment(run_every=2)
                def poll_round_advance():
                    if store["active_round_idx"] != curr_idx:
                        st.rerun()
                        
                poll_round_advance()
            else:
                st.subheader(f"Round {curr_round_num}")
                st.write(f"Playing as: **{st.session_state.my_name}**")
                st.write("Tap the map to place your pin:")
                
                s_lat_key = f"slat_g{store['game_id']}_r{curr_round_num}"
                s_lon_key = f"slon_g{store['game_id']}_r{curr_round_num}"
                
                if s_lat_key not in st.session_state:
                    st.session_state[s_lat_key] = None
                    st.session_state[s_lon_key] = None

                m_student = create_bounded_map(location=[20.0, 0.0], zoom_start=1)
                
                if st.session_state[s_lat_key] is not None:
                    folium.Marker(
                        [st.session_state[s_lat_key], st.session_state[s_lon_key]],
                        icon=folium.Icon(color='red', icon='info-sign')
                    ).add_to(m_student)
                
                student_map_data = st_folium(m_student, height=350, width=350, key=f"smap_g{store['game_id']}_r{curr_round_num}")
                
                if student_map_data and student_map_data.get("last_clicked"):
                    clat = student_map_data["last_clicked"]["lat"]
                    clon = student_map_data["last_clicked"]["lng"]
                    
                    if clat != st.session_state[s_lat_key] or clon != st.session_state[s_lon_key]:
                        st.session_state[s_lat_key] = clat
                        st.session_state[s_lon_key] = clon
                        st.rerun()

                if st.session_state[s_lat_key] is not None:
                    if st.button("LOCK IN GUESS 🔒", use_container_width=True):
                        new_guess = pd.DataFrame([{
                            'round_num': curr_round_num,
                            'name': st.session_state.my_name,
                            'lat': float(st.session_state[s_lat_key]),
                            'lon': float(st.session_state[s_lon_key])
                        }])
                        store["all_guesses"] = pd.concat([store["all_guesses"], new_guess], ignore_index=True)
                        st.session_state[lock_key] = True
                        st.rerun()