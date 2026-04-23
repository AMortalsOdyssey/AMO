# Build stage
FROM node:20-alpine AS builder

ARG cacheDir=/tmp/cache

WORKDIR /app

# Copy package files first (for better layer caching)
# Dependencies change rarely, code changes often
COPY package.json package-lock.json ./

# Install dependencies with cache directory
# Uses platform-provided cache when available
RUN npm config set cache ${cacheDir}/npm && \
    npm ci --registry=https://registry.npmmirror.com

# Copy source code last (changes here won't invalidate dependency cache)
COPY . .

# Build the application (no build-time API_BASE needed, uses relative path by default)
RUN npm run build

# Production stage
FROM node:20-alpine AS runner

WORKDIR /app

ENV NODE_ENV=production

# Create non-root user
RUN addgroup --system --gid 1001 nodejs && \
    adduser --system --uid 1001 nextjs

# Copy built assets
COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs

EXPOSE 3000

ENV PORT=3000
ENV HOSTNAME="0.0.0.0"

CMD ["node", "server.js"]
