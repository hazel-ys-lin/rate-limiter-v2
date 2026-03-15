local ip = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local unique = tonumber(ARGV[4])
local clearBefore = now - window
redis.call('ZREMRANGEBYSCORE', ip, 0, clearBefore)
local amount = redis.call('ZCARD', ip)

if amount < limit then
    redis.call('ZADD', ip, now, unique)
end

redis.call('EXPIRE', ip, window)
return limit - amount