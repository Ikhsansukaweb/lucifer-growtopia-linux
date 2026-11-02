local thread = {}

function runCoroutine(func, ...)
  local co = coroutine.create(func)
  local ok, sleep_timer = coroutine.resume(co, ...)
  if ok and coroutine.status(co) == "suspended" and sleep_timer then
    table.insert(thread, {co = co, timer = getTime() + sleep_timer})
  end
end

runThread = runCoroutine

function __OnDrawLoop__()
  if #thread > 0 then
    for k, v in pairs(thread) do
      if v.timer < getTime() then
        local ok, sleep_timer = coroutine.resume(v.co)
        if coroutine.status(v.co) == "suspended" and sleep_timer then
            v.timer = getTime() + sleep_timer
          else
            table.remove(thread, k)
          end
      end
    end
  end
end