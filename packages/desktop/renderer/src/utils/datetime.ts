/**
 * 时间显示统一入口。
 *
 * 背景（踩过的坑）：后端有一批时间来自数据库列 `timestamp without time zone`，
 * 存的是 naive UTC。裸的 "2026-09-19T13:06:33"（没有 Z、没有 +08:00）交给
 * `new Date()` 会被浏览器按**当地时间**解析 —— 于是同一份检查报告，列表显示
 * 13:06，实际本地时间是 21:06，整整差 8 小时（用户反馈的"报告时间不对"）。
 *
 * 现在后端已经统一输出带时区的 ISO 串（iso_utc / iso_now_local）；这里再兜一层：
 * 万一遇到没有时区标记的旧数据，一律按 UTC 解析，宁可差一次也不放任它当本地时间。
 */

/** 是否带时区信息：以 Z 结尾，或带 +08:00 / -05:00 这类偏移。 */
function hasTimezone(s: string): boolean {
  return /(?:Z|[+-]\d{2}:?\d{2})$/i.test(s.trim());
}

/** 无时区标记时的解释方式。 */
export type NaiveAs = 'utc' | 'local';

/**
 * 解析成 Date。
 *
 * naiveAs 只在"字符串没有时区标记"时起作用，且必须显式选对：
 *  - 'utc'  ：数据库列（checked_at/created_at 等，存的是 UTC）—— 默认
 *  - 'local'：后端用 datetime.now() 写出来的本地时间（如老的 fix-plan 的
 *             generated_at），这类值按 UTC 解析会整体晚 8 小时
 */
export function parseServerTime(
  value?: string | number | Date | null,
  naiveAs: NaiveAs = 'utc'
): Date | null {
  if (value === null || value === undefined || value === '') return null;
  if (value instanceof Date) return isNaN(value.getTime()) ? null : value;
  if (typeof value === 'number') {
    const d = new Date(value);
    return isNaN(d.getTime()) ? null : d;
  }
  const raw = String(value).trim();
  const normalized = hasTimezone(raw)
    ? raw
    : naiveAs === 'utc'
    ? `${raw.replace(' ', 'T')}Z`
    : raw.replace(' ', 'T');
  const d = new Date(normalized);
  return isNaN(d.getTime()) ? null : d;
}

const pad = (n: number) => String(n).padStart(2, '0');

export interface FormatOptions {
  /** 是否显示秒，默认显示 */
  seconds?: boolean;
  /** 无时区标记时按什么解析，默认 utc */
  naiveAs?: NaiveAs;
}

/**
 * 显示成本地时间字符串。
 */
export function formatDateTime(
  value?: string | number | Date | null,
  opts: FormatOptions = {}
): string {
  const d = parseServerTime(value, opts.naiveAs ?? 'utc');
  if (!d) return '';
  const date = `${d.getFullYear()}/${d.getMonth() + 1}/${d.getDate()}`;
  const time = `${pad(d.getHours())}:${pad(d.getMinutes())}${
    opts.seconds === false ? '' : `:${pad(d.getSeconds())}`
  }`;
  return `${date} ${time}`;
}

/** 只要日期：2026/9/19 */
export function formatDate(value?: string | number | Date | null, naiveAs: NaiveAs = 'utc'): string {
  const d = parseServerTime(value, naiveAs);
  if (!d) return '';
  return `${d.getFullYear()}/${d.getMonth() + 1}/${d.getDate()}`;
}

/** 相对时间：刚刚 / 5 分钟前 / 3 小时前 / 2 天前，超过 7 天回退到具体日期 */
export function formatRelative(value?: string | number | Date | null, naiveAs: NaiveAs = 'utc'): string {
  const d = parseServerTime(value, naiveAs);
  if (!d) return '';
  const diff = Date.now() - d.getTime();
  if (diff < 0) return formatDateTime(value, { naiveAs });
  const min = Math.floor(diff / 60000);
  if (min < 1) return '刚刚';
  if (min < 60) return `${min} 分钟前`;
  const hour = Math.floor(min / 60);
  if (hour < 24) return `${hour} 小时前`;
  const day = Math.floor(hour / 24);
  if (day <= 7) return `${day} 天前`;
  return formatDateTime(value, { seconds: false, naiveAs });
}