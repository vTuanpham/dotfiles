export const rfc3339 = (v: unknown) => {
  if (typeof v !== 'string') return false
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.exec(v)
  if (!match) return false
  const year = Number(match[1]), month = Number(match[2]), day = Number(match[3])
  return year >= 1 && month >= 1 && month <= 12 && day >= 1
    && day <= new Date(Date.UTC(year, month, 0)).getUTCDate()
    && Number(match[4]) < 24 && Number(match[5]) < 60 && Number(match[6]) < 60
    && Number.isFinite(Date.parse(v))
}
