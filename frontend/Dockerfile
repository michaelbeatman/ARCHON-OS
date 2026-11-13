FROM node:20-alpine

WORKDIR /app

# Copy package files
COPY package*.json ./

# Install dependencies
RUN npm ci || npm install

# Copy application source
COPY . .

# Build Next.js application
RUN npm run build

EXPOSE 3005

ENV PORT=3005
ENV NODE_ENV=production

CMD ["npm", "run", "start"]
