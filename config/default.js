require('dotenv').config();

module.exports = {
  server: {
    port: process.env.PORT || 3000,
    host: process.env.HOST || '0.0.0.0',
    env: process.env.NODE_ENV || 'development'
  },
  
  flattrade: {
    host: process.env.FLATTRADE_HOST || 'https://piconnect.flattrade.in/PiConnectTP',
    websocket: process.env.FLATTRADE_WEBSOCKET || 'wss://piconnect.flattrade.in/PiConnectWSTp/'
  },
  
  security: {
    sessionSecret: process.env.SESSION_SECRET || 'default-session-secret',
    jwtSecret: process.env.JWT_SECRET || 'default-jwt-secret',
    encryptionKey: process.env.ENCRYPTION_KEY || 'default-encryption-key'
  },
  
  cors: {
    origin: process.env.CORS_ORIGIN || 'http://localhost:3000',
    allowedOrigins: process.env.ALLOWED_ORIGINS ? 
      process.env.ALLOWED_ORIGINS.split(',') : 
      ['http://localhost:3000', 'http://127.0.0.1:3000']
  },
  
  rateLimit: {
    windowMs: parseInt(process.env.RATE_LIMIT_WINDOW_MS) || 15 * 60 * 1000, // 15 minutes
    max: parseInt(process.env.RATE_LIMIT_MAX_REQUESTS) || 100
  },
  
  websocket: {
    maxConnections: parseInt(process.env.WS_MAX_CONNECTIONS) || 100,
    heartbeatInterval: parseInt(process.env.WS_HEARTBEAT_INTERVAL) || 30000,
    connectionTimeout: parseInt(process.env.WS_CONNECTION_TIMEOUT) || 60000
  },
  
  cache: {
    optionChainTtl: parseInt(process.env.OPTION_CHAIN_TTL) || 30000,
    marketDataTtl: parseInt(process.env.MARKET_DATA_TTL) || 1000,
    sessionTtl: parseInt(process.env.SESSION_TTL) || 3600000
  },
  
  logging: {
    level: process.env.LOG_LEVEL || 'info',
    file: process.env.LOG_FILE || 'app.log',
    maxSize: process.env.LOG_MAX_SIZE || '10m',
    maxFiles: parseInt(process.env.LOG_MAX_FILES) || 5
  },
  
  trading: {
    defaultExpiryDays: parseInt(process.env.DEFAULT_EXPIRY_DAYS) || 7,
    maxOrderQuantity: parseInt(process.env.MAX_ORDER_QUANTITY) || 1000,
    orderTimeout: parseInt(process.env.ORDER_TIMEOUT) || 30000
  },
  
  marketData: {
    refreshInterval: parseInt(process.env.MARKET_DATA_REFRESH_INTERVAL) || 1000,
    positionRefreshInterval: parseInt(process.env.POSITION_REFRESH_INTERVAL) || 5000,
    orderRefreshInterval: parseInt(process.env.ORDER_REFRESH_INTERVAL) || 2000
  }
};