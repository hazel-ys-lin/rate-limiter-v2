local key = KEYS[1]
local limit = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local count = redis.call('INCR', key)
if count <= limit then
    redis.call('EXPIRE', key, window * 2, 'NX')
    return 0
else
    return count
end
