FROM node:20-slim

WORKDIR /app

COPY package*.json .
RUN npm install

COPY . .

EXPOSE 3000

# --host: vite's dev server binds to localhost only by default, which is unreachable from
# outside the container even with the port published.
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
