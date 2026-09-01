# 🎙️ Accent GeoGuessr

A fun, lightweight web app built for the English classroom to turn accent recognition into a GeoGuessr-style game! 

## 💡 What is this?
The idea is simple:
1. **The Teacher** projects a video or audio clip of someone speaking English from anywhere in the world.
2. **The Students** scan a QR code on the projector using their phones, open a map, and try to guess where the speaker is from by dropping a pin.
3. The app calculates how close everyone's guesses were using geographic distance and awards points!

*This entire project was vibecoded with Gemini using Python and Streamlit!* 

---

## How It Works

* **Mobile Controllers for Students:** No app downloads needed. Students just scan the QR code on the screen, type in a nickname, and drop pins on their phone map.
* **Projector Panel for the Teacher (`?role=teacher`):** Password-protected panel to set up clips, click the actual origin on the map, run the timer, and reveal where everyone guessed.
* **Drag & Drop Uploads:** Upload `.mp3` or `.mp4` accent clips right inside the browser on the fly.
* **Global Scoring System:** Customized GeoGuessr-style point system—since English accents are spread all across the world, the scoring gives players credit even for partial continent guesses.
* **Leaderboard:** Shows top guesses per round and a podium at the end.

---

## Built With

* **Python**
* **Streamlit** (for the UI and live web hosting)
* **Folium** (for interactive maps)
* **Gemini** (for coding partnership & debugging)

---

## 🚀 How to Run Locally

1. **Clone the repo:**
   ```bash
   git clone [https://github.com/QuentinRauschenbach/accent-geoguessr.git](https://github.com/QuentinRauschenbach/accent-geoguessr.git)
   cd accent-geoguessr