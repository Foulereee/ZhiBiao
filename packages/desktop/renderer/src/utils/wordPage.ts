/**
 * 篇幅换算口径。
 *
 * 用户实测:导出的 .docx 每页约 800 字。全站页数估算统一按这个常量换算,
 * 不要再各写各的(以前结构模板页用的是人工估的 page_target,与真实字数
 * 毫无关系,出现过"模板显示 101 页、实际生成 1099 页")。
 */
export const CHARS_PER_PAGE = 800;

/** 字数 -> 页数(向上取整,至少 1 页) */
export function wordsToPages(words: number): number {
  if (!words || words <= 0) return 0;
  return Math.ceil(words / CHARS_PER_PAGE);
}

/** 页数 -> 字数 */
export function pagesToWords(pages: number): number {
  if (!pages || pages <= 0) return 0;
  return Math.round(pages * CHARS_PER_PAGE);
}

export function formatWords(words: number): string {
  return (words || 0).toLocaleString();
}