import { useEffect, useState } from 'react';

/**
 * 窄屏(手机/小屏平板)检测。
 *
 * 900px 以下按手机处理:侧边栏不再占位,改成可收起的抽屉;头部只留必要信息;
 * 页面里的多列布局折叠成单列。用 matchMedia 而不是监听 resize,避免频繁 re-render。
 */
export function useIsNarrow(query = '(max-width: 900px)') {
  const [narrow, setNarrow] = useState(() =>
    typeof window !== 'undefined' && typeof window.matchMedia === 'function'
      ? window.matchMedia(query).matches
      : false
  );

  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return;
    const mq = window.matchMedia(query);
    setNarrow(mq.matches);
    const onChange = (e: MediaQueryListEvent) => setNarrow(e.matches);
    // Safari < 14 只支持 addListener
    if (typeof mq.addEventListener === 'function') {
      mq.addEventListener('change', onChange);
      return () => mq.removeEventListener('change', onChange);
    }
    mq.addListener(onChange);
    return () => mq.removeListener(onChange);
  }, [query]);

  return narrow;
}

export default useIsNarrow;