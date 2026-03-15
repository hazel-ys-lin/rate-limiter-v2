local ip = KEYS[1]
local now = tonumber(ARGV[1])
local windowSize = tonumber(ARGV[2])
local threshold = tonumber(ARGV[3])
local currentWindow = math.floor(now/1000)
local prev_count = 0
local curr_count = 0

local prev_req = redis.call('get', ip .. tostring(currentWindow - 1))
if prev_req then
    prev_count = prev_req
end
local curr_req = redis.call('get', ip .. tostring(currentWindow))
if curr_req then
    curr_count = curr_req
end

local last_contribute = windowSize - (now - currentWindow * 1000)
local ec = (prev_count * (last_contribute / windowSize)) + curr_count + 1
if ec <= threshold then
    redis.call('incr', ip .. tostring(currentWindow))
    redis.call('expire', ip .. tostring(currentWindow), math.floor(windowSize / 1000) * 2, 'NX')
    return 0
else
    return ec .. " " .. prev_count .. " " .. curr_count
end