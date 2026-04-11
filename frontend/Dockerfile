FROM node:20-alpine

# Install build tools needed for native addons
RUN apk add --no-cache python3 make g++

WORKDIR /app

# Copy package files first to leverage Docker cache
COPY package.json ./

# Install fresh — do NOT copy package-lock.json to force clean Linux resolution
RUN npm install

# Copy source code (after install so node_modules is from the Linux install above)
COPY . .

# Remove any host-compiled node_modules that might have been copied
# (the volume mount in docker-compose will override at runtime anyway)
EXPOSE 3000

# Start Vite dev server — must bind to 0.0.0.0 for Docker port mapping
CMD ["npx", "vite", "--host", "0.0.0.0", "--port", "3000"]
