# ── ChronoSense frontend image ───────────────────────────────────────────────
# Multi-stage: build the Vite/React app, then serve the static bundle with nginx.
# nginx also reverse-proxies /api/ to the api service (see nginx.conf).

# Use the glibc image (not alpine/musl) and install fresh from package.json only.
# A Windows-generated package-lock.json pins the wrong rollup native binary and
# npm's optional-deps bug then skips the Linux one, breaking `vite build`.
FROM node:20 AS build
WORKDIR /app
COPY package.json ./
RUN npm install
COPY . .
RUN npm run build

FROM nginx:alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
