# Serves the Flutter web build and nothing else. The build is staged next to this file as ./site by scripts/deploy_web.sh.
FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY site /usr/share/nginx/html
EXPOSE 8080
