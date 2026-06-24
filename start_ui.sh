#!/bin/bash
cd /home/adityahimaone/apps/idx-realtime-feed
exec /home/adityahimaone/apps/idx-realtime-feed/.venv/bin/python -m streamlit run app.py \
  --server.port 8501 \
  --server.address 127.0.0.1 \
  --server.headless true \
  --server.enableCORS false \
  --server.enableXsrfProtection false
