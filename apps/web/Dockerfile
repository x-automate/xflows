FROM node:20-alpine AS deps
WORKDIR /app
COPY apps/web/package.json ./
RUN npm install

FROM node:20-alpine AS build
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY apps/web/package.json ./package.json
COPY apps/web/index.html ./index.html
COPY apps/web/vite.config.js ./vite.config.js
COPY apps/web/src ./src
COPY packages/xflows-catalog ./packages/xflows-catalog
RUN npm run build

FROM node:20-alpine
WORKDIR /app
RUN npm install -g serve
COPY --from=build /app/dist ./dist
EXPOSE 4173
CMD ["serve", "-s", "dist", "-l", "4173"]
