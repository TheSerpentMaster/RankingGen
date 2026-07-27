# RankingGen

RankingGen is a local-first full-stack web app for creating Shorts-style ranking videos from a topic prompt. It includes:

- a login/signup flow
- a polished cosmo-style dashboard with separate tabs
- a topic prompt plus one-click generation
- local MP4 export in a 9:16 Shorts layout
- API settings for OpenAI and YouTube configuration
- toast notifications and animated UI styling

## Run locally

1. Install dependencies:
   - `pip install -r requirements.txt`
2. Start the app:
   - `python app.py`
3. Open http://localhost:5000

## Notes

- The current local renderer creates a 30-second MP4 using a top-5 ranking slideshow with a polished Shorts layout.
- If you later connect real YouTube publishing credentials, the same app can be extended to upload directly to a configured channel.
