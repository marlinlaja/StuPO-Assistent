FROM nginx:alpine

# Adresse des Backends im Docker-Netzwerk, ohne abschliessenden /
ENV BACKEND_URL=http://backend:8000

COPY index.html config.js styles.css app.js pdf-viewer.js favicon.ico favicon.png /usr/share/nginx/html/
COPY fonts/ /usr/share/nginx/html/fonts/
COPY nginx.conf.template /etc/nginx/templates/default.conf.template

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=5 CMD wget -q -O /dev/null http://127.0.0.1:8000/ || exit 1
