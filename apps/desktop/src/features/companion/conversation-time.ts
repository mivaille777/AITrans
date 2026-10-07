const DAY_MS = 24 * 60 * 60 * 1000

function localCalendarDay(date: Date): number {
  // Compare calendar dates without letting daylight-saving changes affect the age.
  return Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()) / DAY_MS
}

function completedMonths(date: Date, now: Date): number {
  const months = (now.getFullYear() - date.getFullYear()) * 12 + now.getMonth() - date.getMonth()
  const lastDay = new Date(now.getFullYear(), now.getMonth() + 1, 0).getDate()
  return months - (now.getDate() < Math.min(date.getDate(), lastDay) ? 1 : 0)
}

function relativeCount(count: number): string {
  return count === 1 ? "一" : count === 2 ? "两" : String(count)
}

export function formatConversationTime(value: string, now = new Date()): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ""

  const days = localCalendarDay(now) - localCalendarDay(date)
  if (days <= 0) {
    return date.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", hourCycle: "h23" })
  }
  if (days === 1) return "昨天"
  if (days === 2) return "前天"
  if (days < 7) return `${days}天前`

  const months = completedMonths(date, now)
  if (months >= 12) return `${relativeCount(Math.floor(months / 12))}年前`
  if (months >= 1) return `${relativeCount(months)}个月前`
  return `${relativeCount(Math.floor(days / 7))}周前`
}

export function formatConversationTimestamp(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ""

  const parts = new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23",
    timeZoneName: "longOffset",
  }).formatToParts(date)
  const time = parts
    .filter((part) => part.type === "hour" || part.type === "minute" || part.type === "second")
    .map((part) => part.value)
    .join(":")
  const zone = parts.find((part) => part.type === "timeZoneName")?.value ?? ""
  return `${date.getFullYear()}年${date.getMonth() + 1}月${date.getDate()}日 ${time} ${zone}`
}
