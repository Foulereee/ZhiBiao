import { useState, useEffect, useMemo, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Newspaper, Plus, Trash2, Play, Loader2, RefreshCw, Filter, Bell, TrendingUp, Flame, Briefcase,
  Clock, ExternalLink, Zap, Database, Sparkles, ArrowRight, ArrowLeft, Check, X,
  Star, MapPin, DollarSign, Building2, Rocket, Layers, Settings2, BarChart3,
  FileText, Copy, Globe, AlertTriangle,
} from 'lucide-react';
import { newsApi, type Industry, type NewsSource, type Hotspot, type HotspotScoreDetail, type HotspotDetail } from '../services/api';
import { useAppStore } from '../stores/appStore';

interface MonitorTask {
  id: string;
  name: string;
  keywords: string;
  exclude_keywords?: string;
  must_contain_keywords?: string;
  sites: string[];
  enabled: boolean;
  last_run_at?: string;
}

interface NewsItem {
  id?: string;
  title: string;
  url: string;
  pub_date: string;
  source: string;
  content?: string;
  keyword_score?: number;
  relevance_score?: number;
  category?: string;
  is_hot?: boolean;
  hot_score?: number;
  created_at?: string;
}

interface HotItem {
  id: string;
  title: string;
  url: string;
  source: string;
  pub_date: string;
  content: string;
  keyword_score: number;
  relevance_score: number;
  category: string;
  is_hot: boolean;
  hot_score: number;
  created_at: string;
}

type NewsTab = 'tasks' | 'results' | 'today-hot' | 'recommend' | 'sources';
type HotCategory = 'all' | 'hot' | 'business';
// 0 = 快速创建表单, 1-4 = 向导步骤
type WizardStep = 0 | 1 | 2 | 3 | 4;

export default function NewsPage() {
  const navigate = useNavigate();
  const setCurrentProject = useAppStore((s) => s.setCurrentProject);
  const [tasks, setTasks] = useState<MonitorTask[]>([]);
  const [showAdd, setShowAdd] = useState(false);
  const [newName, setNewName] = useState('');
  const [newKeywords, setNewKeywords] = useState('');
  const [newExclude, setNewExclude] = useState('');
  const [newMustContain, setNewMustContain] = useState('');
  const [newSites, setNewSites] = useState('');
  const [newsResults, setNewsResults] = useState<NewsItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [runningTaskId, setRunningTaskId] = useState<string>('');
  const [error, setError] = useState<string>('');
  const [crawlErrors, setCrawlErrors] = useState<Array<{ site: string; error: string; code?: string }>>([]);
  const [aggregateErrors, setAggregateErrors] = useState<Array<{ code: string; error: string }>>([]);
  const [activeTab, setActiveTab] = useState<NewsTab>('recommend');

  const [hotItems, setHotItems] = useState<HotItem[]>([]);
  const [hotCategory, setHotCategory] = useState<HotCategory>('all');
  const [hotLoading, setHotLoading] = useState(false);
  const [hotRefreshing, setHotRefreshing] = useState(false);
  const [hotStats, setHotStats] = useState({ total: 0, hot_count: 0, business_count: 0, date: '' });

  // === Phase 1 新增状态 ===
  const [industries, setIndustries] = useState<Industry[]>([]);
  const [sources, setSources] = useState<NewsSource[]>([]);
  const [sourcesFilter, setSourcesFilter] = useState<string>('all');
  const [sourcesLoading, setSourcesLoading] = useState(false);
  const [syncing, setSyncing] = useState(false);

  const [hotspots, setHotspots] = useState<Hotspot[]>([]);
  const [hotspotsTotal, setHotspotsTotal] = useState(0);
  const [hotspotsLoading, setHotspotsLoading] = useState(false);
  const [aggregating, setAggregating] = useState(false);
  const [hotspotFilter, setHotspotFilter] = useState({
    industry_code: 'all' as string,
    min_score: 0,
    is_hot: undefined as boolean | undefined,
    keyword: '',
  });
  const [scoreDetail, setScoreDetail] = useState<HotspotScoreDetail | null>(null);
  const [hotspotDetail, setHotspotDetail] = useState<HotspotDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [converting, setConverting] = useState<string>('');
  const [toast, setToast] = useState<{ type: 'success' | 'error' | 'warning'; text: string } | null>(null);

  // 4 步向导状态
  const [wizardStep, setWizardStep] = useState<WizardStep>(1);
  const [wizardIndustry, setWizardIndustry] = useState<string>('');
  const [wizardSourceCodes, setWizardSourceCodes] = useState<string[]>([]);
  const [wizardName, setWizardName] = useState('');
  const [wizardKeywords, setWizardKeywords] = useState('');
  const [wizardExclude, setWizardExclude] = useState('');
  const [wizardMustContain, setWizardMustContain] = useState('');

  useEffect(() => {
    loadTasks();
    loadTodayHot();
    loadIndustries();
    loadSources();
    loadHotspots();
  }, []);

  useEffect(() => {
    loadTodayHot();
  }, [hotCategory]);

  useEffect(() => {
    if (activeTab === 'recommend') {
      loadHotspots();
    } else if (activeTab === 'sources') {
      loadSources();
    }
  }, [activeTab]);

  useEffect(() => {
    if (hotspotFilter.industry_code !== 'all' || hotspotFilter.min_score > 0 || hotspotFilter.is_hot !== undefined) {
      loadHotspots();
    }
  }, [hotspotFilter.industry_code, hotspotFilter.min_score, hotspotFilter.is_hot]);

  // 关键词搜索防抖 (500ms)
  const keywordDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => {
    if (keywordDebounceRef.current) {
      clearTimeout(keywordDebounceRef.current);
    }
    keywordDebounceRef.current = setTimeout(() => {
      loadHotspots();
    }, 500);
    return () => {
      if (keywordDebounceRef.current) {
        clearTimeout(keywordDebounceRef.current);
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hotspotFilter.keyword]);

  useEffect(() => {
    if (toast) {
      const t = setTimeout(() => setToast(null), 3500);
      return () => clearTimeout(t);
    }
  }, [toast]);

  const showToast = (type: 'success' | 'error' | 'warning', text: string) => setToast({ type, text });

  // === 基础数据加载 (保持原逻辑) ===
  const loadTasks = async () => {
    try {
      const res = await newsApi.listTasks();
      setTasks(res.data.tasks || []);
    } catch (e) {
      console.error('加载任务失败', e);
    }
  };

  const loadTodayHot = async () => {
    setHotLoading(true);
    try {
      const res = await newsApi.todayHot(hotCategory, 50);
      const data = res.data;
      setHotItems(data.items || []);
      setHotStats({
        total: data.total || 0,
        hot_count: data.hot_count || 0,
        business_count: data.business_count || 0,
        date: data.date || '',
      });
    } catch (e) {
      console.error('加载今日热点失败', e);
    } finally {
      setHotLoading(false);
    }
  };

  const handleRefreshHot = async () => {
    setHotRefreshing(true);
    setError('');
    try {
      const res = await newsApi.refreshHot();
      if (res.data.success) {
        await loadTodayHot();
      } else {
        setError(res.data.message || '刷新失败');
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '刷新失败');
    } finally {
      setHotRefreshing(false);
    }
  };

  // === 基础任务操作 (保持原逻辑) ===
  const handleAddTask = async () => {
    if (!newName.trim() || !newKeywords.trim()) return;
    try {
      await newsApi.createTask({
        name: newName.trim(),
        keywords: newKeywords.trim(),
        sites: newSites.split(',').map(s => s.trim()).filter(Boolean),
      });
      setNewName('');
      setNewKeywords('');
      setNewExclude('');
      setNewMustContain('');
      setNewSites('');
      setShowAdd(false);
      await loadTasks();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '创建任务失败');
    }
  };

  const handleRemoveTask = async (id: string) => {
    try {
      await newsApi.deleteTask(id);
      await loadTasks();
    } catch (e) {
      console.error('删除任务失败', e);
    }
  };

  const handleToggleTask = async (task: MonitorTask) => {
    try {
      await newsApi.updateTask(task.id, { enabled: !task.enabled });
      await loadTasks();
    } catch (e) {
      console.error('更新任务失败', e);
    }
  };

  const handleRunTask = async (taskId: string) => {
    setRunningTaskId(taskId);
    setLoading(true);
    setError('');
    setCrawlErrors([]);
    try {
      const res = await newsApi.runTask(taskId);
      const data = res.data;
      if (data.success) {
        const results = data.data?.results || data.data?.filtered || [];
        setNewsResults(results);
        setActiveTab('results');
        // 展示抓取错误 (如有)
        const errs = data.crawl_errors || [];
        if (errs.length > 0) {
          setCrawlErrors(errs);
        }
        const skipped = data.skipped_api_sites || [];
        const unresolved = data.unresolved_sites || [];
        const totalIssues = errs.length + skipped.length + unresolved.length;
        if (totalIssues > 0) {
          showToast('warning', `抓取完成,但有 ${totalIssues} 个源异常,请查看详情`);
        }
      } else {
        setError(data.error || '执行失败');
        const errs = data.crawl_errors || [];
        if (errs.length > 0) setCrawlErrors(errs);
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '执行失败');
    } finally {
      setLoading(false);
      setRunningTaskId('');
    }
  };

  const handleSemanticFilter = async (taskId: string) => {
    setRunningTaskId(taskId);
    setLoading(true);
    setError('');
    try {
      const res = await newsApi.semanticFilter(taskId, '', 0.6);
      if (res.data.success) {
        const data = res.data.data || {};
        const results = data.filtered || [];
        setNewsResults(results);
        setActiveTab('results');
      } else {
        setError(res.data.error || '语义过滤失败');
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '语义过滤失败');
    } finally {
      setLoading(false);
      setRunningTaskId('');
    }
  };

  const handleViewResults = async (taskId: string) => {
    try {
      const res = await newsApi.listResults(taskId);
      const results = res.data.results || [];
      if (results.length > 0) {
        setNewsResults(results);
        setActiveTab('results');
      }
    } catch (e) {
      console.error('查看结果失败', e);
    }
  };

  // === Phase 1 新增操作 ===
  const loadIndustries = async () => {
    try {
      const res = await newsApi.listIndustries();
      setIndustries(res.data.industries || []);
    } catch (e) {
      console.error('加载行业分类失败', e);
    }
  };

  const loadSources = async () => {
    setSourcesLoading(true);
    try {
      const params: { industry?: string } = {};
      if (sourcesFilter !== 'all') params.industry = sourcesFilter;
      const res = await newsApi.listSources(params);
      setSources(res.data.sources || []);
    } catch (e) {
      console.error('加载数据源失败', e);
    } finally {
      setSourcesLoading(false);
    }
  };

  const loadHotspots = async () => {
    setHotspotsLoading(true);
    try {
      const params: Record<string, unknown> = { limit: 50 };
      if (hotspotFilter.industry_code !== 'all') params.industry_code = hotspotFilter.industry_code;
      if (hotspotFilter.min_score > 0) params.min_score = hotspotFilter.min_score;
      if (hotspotFilter.is_hot !== undefined) params.is_hot = hotspotFilter.is_hot;
      if (hotspotFilter.keyword.trim()) params.keyword = hotspotFilter.keyword.trim();
      const res = await newsApi.listHotspots(params);
      setHotspots(res.data.items || []);
      setHotspotsTotal(res.data.total || 0);
    } catch (e) {
      console.error('加载智能推荐失败', e);
    } finally {
      setHotspotsLoading(false);
    }
  };

  const handleSyncSources = async () => {
    setSyncing(true);
    try {
      const res = await newsApi.syncSources();
      showToast('success', res.data.message || '同步成功');
      await loadSources();
    } catch (e: unknown) {
      showToast('error', e instanceof Error ? e.message : '同步失败');
    } finally {
      setSyncing(false);
    }
  };

  const handleToggleSource = async (src: NewsSource) => {
    try {
      await newsApi.toggleSource(src.code, !src.enabled);
      showToast('success', `${src.name} 已${!src.enabled ? '启用' : '禁用'}`);
      await loadSources();
    } catch (e: unknown) {
      showToast('error', e instanceof Error ? e.message : '操作失败');
    }
  };

  const handleAggregate = async () => {
    setAggregating(true);
    setAggregateErrors([]);
    try {
      const res = await newsApi.aggregate({});
      const data = res.data;
      if (data.success) {
        const errs = data.errors || [];
        if (errs.length > 0) {
          setAggregateErrors(errs);
          showToast('warning', `聚合完成,共 ${data.total} 条,入库 ${data.saved} 条,但有 ${errs.length} 个源异常`);
        } else {
          showToast('success', `聚合完成,共 ${data.total} 条,入库 ${data.saved} 条`);
        }
        await loadHotspots();
      } else {
        showToast('error', data.message || data.error || '聚合失败');
        const errs = data.errors || [];
        if (errs.length > 0) setAggregateErrors(errs);
      }
    } catch (e: unknown) {
      showToast('error', e instanceof Error ? e.message : '聚合失败');
    } finally {
      setAggregating(false);
    }
  };

  const handleAggregateIndustry = async (industryCode: string) => {
    setAggregating(true);
    try {
      const res = await newsApi.aggregate({ industry_code: industryCode });
      const data = res.data;
      if (data.success) {
        showToast('success', `${getIndustryDisplayName(industryCode)} 聚合完成,共 ${data.total} 条,入库 ${data.saved} 条`);
        await loadHotspots();
      } else {
        showToast('error', data.message || data.error || '聚合失败');
      }
    } catch (e: unknown) {
      showToast('error', e instanceof Error ? e.message : '聚合失败');
    } finally {
      setAggregating(false);
    }
  };

  const handleViewScore = async (id: string) => {
    try {
      const res = await newsApi.getHotspotScore(id);
      setScoreDetail(res.data);
    } catch (e: unknown) {
      showToast('error', e instanceof Error ? e.message : '加载评分失败');
    }
  };

  const handleViewDetail = async (id: string) => {
    setDetailLoading(true);
    setHotspotDetail(null);
    try {
      const res = await newsApi.getHotspotDetail(id);
      setHotspotDetail(res.data);
    } catch (e: unknown) {
      showToast('error', e instanceof Error ? e.message : '加载详情失败');
    } finally {
      setDetailLoading(false);
    }
  };

  const handleConvertToBid = async (id: string) => {
    setConverting(id);
    try {
      const res = await newsApi.convertHotspotToBid(id, {});
      if (res.data.success) {
        const newProjectId = res.data.project_id;
        const newProjectName = res.data.project_name || '新项目';
        showToast('success', `已创建"${newProjectName}",即将跳转到标书生成...`);
        await loadHotspots();
        // 切换当前项目并跳转到生成页
        if (newProjectId) {
          setCurrentProject(newProjectId);
          setTimeout(() => navigate('/generate'), 800);
        }
      } else {
        showToast('error', res.data.message || '转换失败');
      }
    } catch (e: unknown) {
      showToast('error', e instanceof Error ? e.message : '转换失败');
    } finally {
      setConverting('');
    }
  };

  // === 4 步向导 ===
  const wizardSources = useMemo(() => {
    if (!wizardIndustry) return sources;
    return sources.filter(s => s.industry_code === wizardIndustry || s.industry_code?.startsWith(wizardIndustry));
  }, [sources, wizardIndustry]);

  const resetWizard = () => {
    setWizardStep(1);
    setWizardIndustry('');
    setWizardSourceCodes([]);
    setWizardName('');
    setWizardKeywords('');
    setWizardExclude('');
    setWizardMustContain('');
  };

  const handleWizardSubmit = async () => {
    if (!wizardName.trim() || !wizardKeywords.trim()) {
      showToast('error', '请填写任务名称和关键词');
      return;
    }
    try {
      await newsApi.createTask({
        name: wizardName.trim(),
        keywords: wizardKeywords.trim(),
        sites: wizardSourceCodes,
      });
      showToast('success', '任务创建成功');
      resetWizard();
      setShowAdd(false);
      await loadTasks();
    } catch (e: unknown) {
      showToast('error', e instanceof Error ? e.message : '创建任务失败');
    }
  };

  // === 辅助函数 ===
  const getIndustryDisplayName = (code: string): string => {
    if (!code) return '';
    for (const cat of industries) {
      if (cat.code === code) return `${cat.icon || ''} ${cat.name}`;
      for (const sub of cat.children || []) {
        if (sub.code === code) return `${cat.icon || ''} ${cat.name}/${sub.name}`;
      }
    }
    return code;
  };

  const getCategoryBadge = (category: string) => {
    if (category === 'hot') {
      return (
        <span style={{ padding: '2px 8px', borderRadius: '10px', fontSize: '11px', background: '#fef2f2', color: '#dc2626', fontWeight: 600, display: 'inline-flex', alignItems: 'center', gap: '3px' }}>
          <Flame size={10} /> 热点
        </span>
      );
    }
    if (category === 'business') {
      return (
        <span style={{ padding: '2px 8px', borderRadius: '10px', fontSize: '11px', background: '#eff6ff', color: '#2563eb', fontWeight: 600, display: 'inline-flex', alignItems: 'center', gap: '3px' }}>
          <Briefcase size={10} /> 商机
        </span>
      );
    }
    return (
      <span style={{ padding: '2px 8px', borderRadius: '10px', fontSize: '11px', background: '#f0fdf4', color: '#16a34a', fontWeight: 500 }}>
        一般
      </span>
    );
  };

  const getHotScoreColor = (score: number) => {
    if (score >= 0.8) return '#dc2626';
    if (score >= 0.6) return '#d97706';
    if (score >= 0.4) return '#2563eb';
    return '#6b7280';
  };

  const getScoreColor = (s: number) => {
    if (s >= 80) return '#dc2626';
    if (s >= 60) return '#d97706';
    if (s >= 40) return '#2563eb';
    return '#6b7280';
  };

  const formatAmount = (amount: number) => {
    if (!amount) return '-';
    if (amount >= 1e8) return `${(amount / 1e8).toFixed(2)} 亿元`;
    if (amount >= 1e4) return `${(amount / 1e4).toFixed(2)} 万元`;
    return `${amount} 元`;
  };

  // ============================================================
  // 渲染: 今日热点 tab (保持原逻辑)
  // ============================================================
  const renderTodayHotTab = () => (
    <div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '12px', marginBottom: '20px' }}>
        <div style={{ padding: '16px', background: 'linear-gradient(135deg, #fef2f2, #fff1f2)', borderRadius: '12px', border: '1px solid #fecaca' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '8px' }}>
            <Flame size={18} color="#dc2626" />
            <span style={{ fontSize: '13px', color: '#991b1b', fontWeight: 500 }}>今日热点</span>
          </div>
          <div style={{ fontSize: '32px', fontWeight: 700, color: '#dc2626' }}>{hotStats.hot_count}</div>
          <div style={{ fontSize: '11px', color: '#b91c1c', marginTop: '2px' }}>紧急/重要招标信息</div>
        </div>
        <div style={{ padding: '16px', background: 'linear-gradient(135deg, #eff6ff, #e0f2fe)', borderRadius: '12px', border: '1px solid #bfdbfe' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '8px' }}>
            <Briefcase size={18} color="#2563eb" />
            <span style={{ fontSize: '13px', color: '#1e40af', fontWeight: 500 }}>今日商机</span>
          </div>
          <div style={{ fontSize: '32px', fontWeight: 700, color: '#2563eb' }}>{hotStats.business_count}</div>
          <div style={{ fontSize: '11px', color: '#1d4ed8', marginTop: '2px' }}>招标/采购/中标机会</div>
        </div>
        <div style={{ padding: '16px', background: 'linear-gradient(135deg, #f0fdf4, #dcfce7)', borderRadius: '12px', border: '1px solid #bbf7d0' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '8px' }}>
            <Newspaper size={18} color="#16a34a" />
            <span style={{ fontSize: '13px', color: '#166534', fontWeight: 500 }}>今日总计</span>
          </div>
          <div style={{ fontSize: '32px', fontWeight: 700, color: '#16a34a' }}>{hotStats.total}</div>
          <div style={{ fontSize: '11px', color: '#15803d', marginTop: '2px' }}>{hotStats.date} 采集总量</div>
        </div>
      </div>

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
        <div style={{ display: 'flex', gap: '6px' }}>
          {([
            { key: 'all' as HotCategory, label: '全部', icon: <Newspaper size={13} /> },
            { key: 'hot' as HotCategory, label: '热点', icon: <Flame size={13} /> },
            { key: 'business' as HotCategory, label: '商机', icon: <Briefcase size={13} /> },
          ]).map(cat => (
            <button
              key={cat.key}
              onClick={() => setHotCategory(cat.key)}
              style={{
                padding: '6px 14px',
                background: hotCategory === cat.key ? 'var(--color-primary)' : 'var(--color-surface)',
                color: hotCategory === cat.key ? 'white' : 'var(--color-text)',
                border: `1px solid ${hotCategory === cat.key ? 'var(--color-primary)' : 'var(--color-border)'}`,
                borderRadius: '6px',
                cursor: 'pointer',
                fontSize: '12px',
                fontWeight: 500,
                display: 'flex',
                alignItems: 'center',
                gap: '4px',
              }}
            >
              {cat.icon} {cat.label}
            </button>
          ))}
        </div>
        <button
          onClick={handleRefreshHot}
          disabled={hotRefreshing}
          style={{
            padding: '6px 14px',
            background: hotRefreshing ? '#94a3b8' : '#475569',
            color: 'white',
            border: 'none',
            borderRadius: '6px',
            cursor: hotRefreshing ? 'not-allowed' : 'pointer',
            fontSize: '12px',
            fontWeight: 500,
            display: 'flex',
            alignItems: 'center',
            gap: '4px',
          }}
        >
          {hotRefreshing ? <Loader2 size={13} /> : <Zap size={13} />} {hotRefreshing ? '刷新中...' : '立即刷新'}
        </button>
      </div>

      {hotLoading ? (
        <div style={{ textAlign: 'center', padding: '40px', color: 'var(--color-text-secondary)' }}>
          <Loader2 size={24} style={{ animation: 'spin 1s linear infinite' }} />
          <div style={{ marginTop: '8px', fontSize: '13px' }}>加载中...</div>
        </div>
      ) : hotItems.length === 0 ? (
        <div style={{ textAlign: 'center', padding: '60px', color: 'var(--color-text-secondary)', background: 'var(--color-surface)', borderRadius: '12px', border: '1px solid var(--color-border)' }}>
          <TrendingUp size={48} color="#cbd5e1" style={{ margin: '0 auto 12px' }} />
          <div style={{ fontSize: '14px', fontWeight: 500, marginBottom: '4px' }}>今日暂无热点数据</div>
          <div style={{ fontSize: '12px' }}>点击"立即刷新"从监控任务中获取最新招标信息</div>
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          {hotItems.map((item, idx) => (
            <div
              key={item.id || idx}
              style={{
                padding: '14px 16px',
                background: 'var(--color-surface)',
                border: '1px solid var(--color-border)',
                borderRadius: '10px',
                borderLeft: item.is_hot ? '3px solid #dc2626' : item.category === 'business' ? '3px solid #2563eb' : '3px solid #16a34a',
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '12px' }}>
                <div style={{ flex: 1 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '4px' }}>
                    <span style={{ fontSize: '12px', color: 'var(--color-text-secondary)', minWidth: '24px' }}>#{idx + 1}</span>
                    {getCategoryBadge(item.category)}
                    <a href={item.url} target="_blank" rel="noopener noreferrer" style={{ fontSize: '14px', fontWeight: 500, color: 'var(--color-text)', textDecoration: 'none', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {item.title}
                    </a>
                    <a href={item.url} target="_blank" rel="noopener noreferrer" style={{ color: 'var(--color-text-secondary)', flexShrink: 0 }}>
                      <ExternalLink size={13} />
                    </a>
                  </div>
                  {item.content && (
                    <div style={{ fontSize: '12px', color: 'var(--color-text-secondary)', marginTop: '4px', lineHeight: '1.6', maxHeight: '48px', overflow: 'hidden', paddingLeft: '32px' }}>
                      {item.content.substring(0, 150)}...
                    </div>
                  )}
                  <div style={{ fontSize: '11px', color: 'var(--color-text-secondary)', marginTop: '6px', display: 'flex', gap: '12px', paddingLeft: '32px' }}>
                    {item.pub_date && (
                      <span style={{ display: 'flex', alignItems: 'center', gap: '3px' }}>
                        <Clock size={10} /> {item.pub_date}
                      </span>
                    )}
                    {item.source && <span>来源: {item.source.length > 25 ? item.source.substring(0, 25) + '...' : item.source}</span>}
                    {item.keyword_score > 0 && <span style={{ color: '#059669' }}>关键词: {item.keyword_score.toFixed(1)}</span>}
                    {item.relevance_score > 0 && <span style={{ color: '#475569' }}>AI: {(item.relevance_score * 100).toFixed(0)}%</span>}
                  </div>
                </div>
                <div style={{ flexShrink: 0, textAlign: 'center', minWidth: '56px' }}>
                  <div style={{ fontSize: '18px', fontWeight: 700, color: getHotScoreColor(item.hot_score) }}>
                    {item.hot_score.toFixed(1)}
                  </div>
                  <div style={{ fontSize: '10px', color: 'var(--color-text-secondary)' }}>热度</div>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );

  // ============================================================
  // 渲染: 任务管理 tab (保留原表单 + 新增 4 步向导按钮)
  // ============================================================
  const renderTasksTab = () => (
    <div style={{ background: 'var(--color-surface)', borderRadius: '12px', padding: '24px', border: '1px solid var(--color-border)' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
        <h3 style={{ fontSize: '16px', fontWeight: 600 }}>监控任务</h3>
        <div style={{ display: 'flex', gap: '8px' }}>
          <button onClick={loadTasks} style={{ padding: '6px 10px', background: 'var(--color-surface)', border: '1px solid var(--color-border)', borderRadius: '6px', cursor: 'pointer' }}>
            <RefreshCw size={14} />
          </button>
          <button
            onClick={() => { resetWizard(); setShowAdd(true); setWizardStep(1); }}
            style={{ padding: '6px 14px', background: 'linear-gradient(135deg, #1a56db, #1e40af)', color: 'white', border: 'none', borderRadius: '6px', cursor: 'pointer', fontSize: '13px', display: 'flex', alignItems: 'center', gap: '4px' }}
          >
            <Sparkles size={14} /> 4步向导创建
          </button>
          <button
            onClick={() => setShowAdd(true)}
            style={{ padding: '6px 14px', background: 'var(--color-primary)', color: 'white', border: 'none', borderRadius: '6px', cursor: 'pointer', fontSize: '13px', display: 'flex', alignItems: 'center', gap: '4px' }}
          >
            <Plus size={14} /> 快速创建
          </button>
        </div>
      </div>

      {showAdd && wizardStep === 0 && (
        <div style={{ marginBottom: '16px', padding: '16px', border: '1px solid var(--color-border)', borderRadius: '8px' }}>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px', marginBottom: '12px' }}>
            <div>
              <label style={{ fontSize: '13px', color: 'var(--color-text-secondary)', display: 'block', marginBottom: '4px' }}>任务名称</label>
              <input type="text" value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="如：智慧城市项目监控" style={{ width: '100%', padding: '8px 12px', border: '1px solid var(--color-border)', borderRadius: '6px', fontSize: '14px', boxSizing: 'border-box' }} />
            </div>
            <div>
              <label style={{ fontSize: '13px', color: 'var(--color-text-secondary)', display: 'block', marginBottom: '4px' }}>包含关键词(逗号分隔)</label>
              <input type="text" value={newKeywords} onChange={(e) => setNewKeywords(e.target.value)} placeholder="智慧城市,数字化" style={{ width: '100%', padding: '8px 12px', border: '1px solid var(--color-border)', borderRadius: '6px', fontSize: '14px', boxSizing: 'border-box' }} />
            </div>
            <div>
              <label style={{ fontSize: '13px', color: 'var(--color-text-secondary)', display: 'block', marginBottom: '4px' }}>排除关键词(可选)</label>
              <input type="text" value={newExclude} onChange={(e) => setNewExclude(e.target.value)} placeholder="已结束,流标" style={{ width: '100%', padding: '8px 12px', border: '1px solid var(--color-border)', borderRadius: '6px', fontSize: '14px', boxSizing: 'border-box' }} />
            </div>
            <div>
              <label style={{ fontSize: '13px', color: 'var(--color-text-secondary)', display: 'block', marginBottom: '4px' }}>必含关键词(可选)</label>
              <input type="text" value={newMustContain} onChange={(e) => setNewMustContain(e.target.value)} placeholder="必须包含的词" style={{ width: '100%', padding: '8px 12px', border: '1px solid var(--color-border)', borderRadius: '6px', fontSize: '14px', boxSizing: 'border-box' }} />
            </div>
          </div>
          <div style={{ marginBottom: '12px' }}>
            <label style={{ fontSize: '13px', color: 'var(--color-text-secondary)', display: 'block', marginBottom: '4px' }}>监控网站(逗号分隔，可选)</label>
            <input type="text" value={newSites} onChange={(e) => setNewSites(e.target.value)} placeholder="ccgp.gov.cn,chinabidding.cn" style={{ width: '100%', padding: '8px 12px', border: '1px solid var(--color-border)', borderRadius: '6px', fontSize: '14px', boxSizing: 'border-box' }} />
          </div>
          <div style={{ display: 'flex', gap: '8px' }}>
            <button onClick={handleAddTask} style={{ padding: '6px 16px', background: '#059669', color: 'white', border: 'none', borderRadius: '6px', cursor: 'pointer', fontSize: '13px' }}>确认创建</button>
            <button onClick={() => setShowAdd(false)} style={{ padding: '6px 16px', background: 'var(--color-surface)', color: 'var(--color-text)', border: '1px solid var(--color-border)', borderRadius: '6px', cursor: 'pointer', fontSize: '13px' }}>取消</button>
          </div>
        </div>
      )}

      {showAdd && wizardStep > 0 && renderWizard()}

      {tasks.length === 0 ? (
        <p style={{ color: 'var(--color-text-secondary)', textAlign: 'center', padding: '24px', fontSize: '14px' }}>暂无监控任务,点击"4步向导创建"开始</p>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          {tasks.map(task => (
            <div key={task.id} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '12px 16px', border: '1px solid var(--color-border)', borderRadius: '8px', opacity: task.enabled ? 1 : 0.5 }}>
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: '14px', fontWeight: 500 }}>{task.name}</div>
                <div style={{ fontSize: '12px', color: 'var(--color-text-secondary)', marginTop: '2px' }}>
                  关键词：{task.keywords}
                  {task.sites && task.sites.length > 0 && ` | 网站：${task.sites.join(', ')}`}
                  {task.last_run_at && ` | 上次运行：${new Date(task.last_run_at).toLocaleString()}`}
                </div>
              </div>
              <div style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>
                <button onClick={() => handleRunTask(task.id)} disabled={runningTaskId === task.id} style={{ padding: '4px 10px', background: '#2563eb', color: 'white', border: 'none', borderRadius: '4px', cursor: runningTaskId === task.id ? 'not-allowed' : 'pointer', fontSize: '12px', display: 'flex', alignItems: 'center', gap: '4px' }}>
                  {runningTaskId === task.id ? <Loader2 size={12} /> : <Play size={12} />} 爬取
                </button>
                <button onClick={() => handleSemanticFilter(task.id)} disabled={runningTaskId === task.id} style={{ padding: '4px 10px', background: '#475569', color: 'white', border: 'none', borderRadius: '4px', cursor: runningTaskId === task.id ? 'not-allowed' : 'pointer', fontSize: '12px', display: 'flex', alignItems: 'center', gap: '4px' }}>
                  <Filter size={12} /> AI过滤
                </button>
                <button onClick={() => handleViewResults(task.id)} style={{ padding: '4px 10px', background: '#0f766e', color: 'white', border: 'none', borderRadius: '4px', cursor: 'pointer', fontSize: '12px' }}>
                  查看
                </button>
                <button onClick={() => handleToggleTask(task)} style={{ padding: '4px 10px', background: task.enabled ? '#ecfdf5' : '#f8fafc', color: task.enabled ? '#059669' : '#6b7280', border: '1px solid var(--color-border)', borderRadius: '4px', cursor: 'pointer', fontSize: '12px' }}>
                  {task.enabled ? '已启用' : '已禁用'}
                </button>
                <button onClick={() => handleRemoveTask(task.id)} style={{ padding: '4px 8px', background: '#fef2f2', color: '#dc2626', border: 'none', borderRadius: '4px', cursor: 'pointer' }}>
                  <Trash2 size={14} />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );

  // ============================================================
  // 渲染: 4 步向导
  // ============================================================
  const renderWizard = () => {
    const stepLabels = [
      { num: 1, label: '选择行业', icon: <Layers size={14} /> },
      { num: 2, label: '选择数据源', icon: <Database size={14} /> },
      { num: 3, label: '设置关键词', icon: <Settings2 size={14} /> },
      { num: 4, label: '确认创建', icon: <Check size={14} /> },
    ];

    return (
      <div style={{ marginBottom: '16px', padding: '20px', border: '1px solid #bfdbfe', borderRadius: '12px', background: 'linear-gradient(135deg, #eff6ff, #eff6ff)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '16px' }}>
          <Sparkles size={16} color="#1a56db" />
          <span style={{ fontSize: '14px', fontWeight: 600, color: '#1e3a8a' }}>4 步向导创建监控任务</span>
        </div>

        {/* 步骤指示器 */}
        <div style={{ display: 'flex', alignItems: 'center', marginBottom: '20px', gap: '4px' }}>
          {stepLabels.map((s, idx) => (
            <div key={s.num} style={{ display: 'flex', alignItems: 'center', flex: 1 }}>
              <div style={{
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
                padding: '6px 12px',
                background: wizardStep >= s.num ? '#1a56db' : '#dbeafe',
                color: wizardStep >= s.num ? 'white' : '#1a56db',
                borderRadius: '6px',
                fontSize: '12px',
                fontWeight: 600,
                flexShrink: 0,
              }}>
                {wizardStep > s.num ? <Check size={12} /> : s.icon} {s.label}
              </div>
              {idx < stepLabels.length - 1 && (
                <div style={{ flex: 1, height: '2px', background: wizardStep > s.num ? '#1a56db' : '#dbeafe', margin: '0 4px' }} />
              )}
            </div>
          ))}
        </div>

        {/* 步骤 1: 选行业 */}
        {wizardStep === 1 && (
          <div>
            <div style={{ fontSize: '13px', color: 'var(--color-text-secondary)', marginBottom: '12px' }}>选择你关注的行业分类(可跳过,选择"全部"将使用所有数据源)</div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '10px', maxHeight: '320px', overflowY: 'auto' }}>
              <div
                onClick={() => setWizardIndustry('')}
                style={{
                  padding: '12px',
                  border: wizardIndustry === '' ? '2px solid #1a56db' : '1px solid var(--color-border)',
                  borderRadius: '8px',
                  background: wizardIndustry === '' ? '#eff6ff' : 'white',
                  cursor: 'pointer',
                  textAlign: 'center',
                  fontSize: '13px',
                  fontWeight: wizardIndustry === '' ? 600 : 400,
                }}
              >
                🌐 全部行业
              </div>
              {industries.map(cat => (
                <div
                  key={cat.code}
                  onClick={() => setWizardIndustry(cat.code)}
                  style={{
                    padding: '12px',
                    border: wizardIndustry === cat.code ? '2px solid #1a56db' : '1px solid var(--color-border)',
                    borderRadius: '8px',
                    background: wizardIndustry === cat.code ? '#eff6ff' : 'white',
                    cursor: 'pointer',
                    textAlign: 'center',
                  }}
                >
                  <div style={{ fontSize: '20px' }}>{cat.icon}</div>
                  <div style={{ fontSize: '12px', fontWeight: wizardIndustry === cat.code ? 600 : 500, marginTop: '4px' }}>{cat.name}</div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* 步骤 2: 选数据源 */}
        {wizardStep === 2 && (
          <div>
            <div style={{ fontSize: '13px', color: 'var(--color-text-secondary)', marginBottom: '12px' }}>
              选择了 <strong>{wizardIndustry ? getIndustryDisplayName(wizardIndustry) : '全部行业'}</strong>,
              可用的数据源 ({wizardSources.length} 个):
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', maxHeight: '320px', overflowY: 'auto' }}>
              {wizardSources.length === 0 && <div style={{ color: 'var(--color-text-secondary)', textAlign: 'center', padding: '24px' }}>该行业下暂无数据源,请选择其他行业</div>}
              {wizardSources.map(src => {
                const checked = wizardSourceCodes.includes(src.code);
                return (
                  <div
                    key={src.code}
                    onClick={() => {
                      if (checked) setWizardSourceCodes(wizardSourceCodes.filter(c => c !== src.code));
                      else setWizardSourceCodes([...wizardSourceCodes, src.code]);
                    }}
                    style={{
                      padding: '12px',
                      border: checked ? '2px solid #1a56db' : '1px solid var(--color-border)',
                      borderRadius: '8px',
                      background: checked ? '#eff6ff' : 'white',
                      cursor: 'pointer',
                      display: 'flex',
                      alignItems: 'center',
                      gap: '10px',
                    }}
                  >
                    <div style={{ width: '18px', height: '18px', border: checked ? 'none' : '2px solid #cbd5e1', background: checked ? '#1a56db' : 'white', borderRadius: '4px', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                      {checked && <Check size={12} color="white" />}
                    </div>
                    <div style={{ flex: 1 }}>
                      <div style={{ fontSize: '13px', fontWeight: 500 }}>{src.name}</div>
                      <div style={{ fontSize: '11px', color: 'var(--color-text-secondary)', marginTop: '2px' }}>
                        {src.type.toUpperCase()} | {getIndustryDisplayName(src.industry_code)} | 权重 {src.weight}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
            <div style={{ marginTop: '8px', fontSize: '12px', color: '#1a56db' }}>已选 {wizardSourceCodes.length} 个数据源</div>
          </div>
        )}

        {/* 步骤 3: 关键词 */}
        {wizardStep === 3 && (
          <div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
              <div style={{ gridColumn: 'span 2' }}>
                <label style={{ fontSize: '13px', color: 'var(--color-text-secondary)', display: 'block', marginBottom: '4px' }}>任务名称 *</label>
                <input type="text" value={wizardName} onChange={(e) => setWizardName(e.target.value)} placeholder="如:医院信息化项目监控" style={{ width: '100%', padding: '8px 12px', border: '1px solid var(--color-border)', borderRadius: '6px', fontSize: '14px', boxSizing: 'border-box' }} />
              </div>
              <div style={{ gridColumn: 'span 2' }}>
                <label style={{ fontSize: '13px', color: 'var(--color-text-secondary)', display: 'block', marginBottom: '4px' }}>包含关键词 * (逗号分隔)</label>
                <input type="text" value={wizardKeywords} onChange={(e) => setWizardKeywords(e.target.value)} placeholder="信息化,医院,软件" style={{ width: '100%', padding: '8px 12px', border: '1px solid var(--color-border)', borderRadius: '6px', fontSize: '14px', boxSizing: 'border-box' }} />
              </div>
              <div>
                <label style={{ fontSize: '13px', color: 'var(--color-text-secondary)', display: 'block', marginBottom: '4px' }}>排除关键词 (可选)</label>
                <input type="text" value={wizardExclude} onChange={(e) => setWizardExclude(e.target.value)} placeholder="已结束,流标" style={{ width: '100%', padding: '8px 12px', border: '1px solid var(--color-border)', borderRadius: '6px', fontSize: '14px', boxSizing: 'border-box' }} />
              </div>
              <div>
                <label style={{ fontSize: '13px', color: 'var(--color-text-secondary)', display: 'block', marginBottom: '4px' }}>必含关键词 (可选)</label>
                <input type="text" value={wizardMustContain} onChange={(e) => setWizardMustContain(e.target.value)} placeholder="必须出现的词" style={{ width: '100%', padding: '8px 12px', border: '1px solid var(--color-border)', borderRadius: '6px', fontSize: '14px', boxSizing: 'border-box' }} />
              </div>
            </div>
          </div>
        )}

        {/* 步骤 4: 确认 */}
        {wizardStep === 4 && (
          <div>
            <div style={{ padding: '16px', background: 'white', border: '1px solid var(--color-border)', borderRadius: '8px' }}>
              <div style={{ fontSize: '13px', fontWeight: 600, marginBottom: '12px' }}>📋 创建确认</div>
              <div style={{ display: 'grid', gridTemplateColumns: '120px 1fr', gap: '10px 16px', fontSize: '13px' }}>
                <span style={{ color: 'var(--color-text-secondary)' }}>任务名称</span>
                <span style={{ fontWeight: 500 }}>{wizardName || '(未填写)'}</span>
                <span style={{ color: 'var(--color-text-secondary)' }}>行业</span>
                <span>{wizardIndustry ? getIndustryDisplayName(wizardIndustry) : '全部行业'}</span>
                <span style={{ color: 'var(--color-text-secondary)' }}>数据源</span>
                <span>{wizardSourceCodes.length} 个 ({wizardSourceCodes.slice(0, 3).join(', ')}{wizardSourceCodes.length > 3 ? '...' : ''})</span>
                <span style={{ color: 'var(--color-text-secondary)' }}>关键词</span>
                <span>{wizardKeywords || '(未填写)'}</span>
                <span style={{ color: 'var(--color-text-secondary)' }}>排除词</span>
                <span>{wizardExclude || '-'}</span>
                <span style={{ color: 'var(--color-text-secondary)' }}>必含词</span>
                <span>{wizardMustContain || '-'}</span>
              </div>
            </div>
          </div>
        )}

        {/* 步骤导航 */}
        <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: '20px' }}>
          <button
            onClick={() => {
              if (wizardStep > 1) setWizardStep((wizardStep - 1) as WizardStep);
              else { resetWizard(); setShowAdd(false); }
            }}
            style={{ padding: '8px 16px', background: 'var(--color-surface)', border: '1px solid var(--color-border)', borderRadius: '6px', cursor: 'pointer', fontSize: '13px', display: 'flex', alignItems: 'center', gap: '4px' }}
          >
            <ArrowLeft size={14} /> {wizardStep === 1 ? '取消' : '上一步'}
          </button>
          {wizardStep < 4 ? (
            <button
              onClick={() => setWizardStep((wizardStep + 1) as WizardStep)}
              style={{ padding: '8px 16px', background: '#1a56db', color: 'white', border: 'none', borderRadius: '6px', cursor: 'pointer', fontSize: '13px', display: 'flex', alignItems: 'center', gap: '4px' }}
            >
              下一步 <ArrowRight size={14} />
            </button>
          ) : (
            <button
              onClick={handleWizardSubmit}
              style={{ padding: '8px 16px', background: 'linear-gradient(135deg, #059669, #10b981)', color: 'white', border: 'none', borderRadius: '6px', cursor: 'pointer', fontSize: '13px', display: 'flex', alignItems: 'center', gap: '4px' }}
            >
              <Check size={14} /> 确认创建
            </button>
          )}
        </div>
      </div>
    );
  };

  // ============================================================
  // 渲染: 采集结果 tab (保持原逻辑)
  // ============================================================
  const renderResultsTab = () => (
    <div style={{ background: 'var(--color-surface)', borderRadius: '12px', padding: '24px', border: '1px solid var(--color-border)' }}>
      <h3 style={{ fontSize: '16px', fontWeight: 600, marginBottom: '16px' }}>采集结果 ({newsResults.length})</h3>
      {/* 抓取错误/异常源提示 */}
      {crawlErrors.length > 0 && (
        <div style={{ marginBottom: '16px', padding: '12px 16px', background: '#fffbeb', border: '1px solid #fbbf24', borderRadius: '8px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px', fontSize: '13px', fontWeight: 600, color: '#92400e' }}>
            <AlertTriangle size={14} /> 以下数据源抓取失败 ({crawlErrors.length} 个)
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
            {crawlErrors.map((e, i) => (
              <div key={i} style={{ fontSize: '12px', color: '#78350f', display: 'flex', gap: '6px', alignItems: 'flex-start' }}>
                <span style={{ color: '#dc2626', flexShrink: 0 }}>✗</span>
                <span><b>{e.site || e.code || '未知源'}</b>: {e.error}</span>
              </div>
            ))}
          </div>
          <div style={{ marginTop: '8px', fontSize: '11px', color: '#92400e' }}>
            提示: 可在"数据源管理"中更换地址或禁用失效源
          </div>
        </div>
      )}
      {newsResults.length === 0 ? (
        <p style={{ color: 'var(--color-text-secondary)', textAlign: 'center', padding: '24px', fontSize: '14px' }}>运行监控任务后查看采集结果</p>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          {newsResults.map((item, idx) => (
            <div key={idx} style={{ padding: '12px 16px', border: '1px solid var(--color-border)', borderRadius: '8px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                <div style={{ flex: 1 }}>
                  <a href={item.url} target="_blank" rel="noopener noreferrer" style={{ fontSize: '14px', fontWeight: 500, color: '#2563eb', textDecoration: 'none' }}>
                    {item.title}
                  </a>
                  <div style={{ fontSize: '12px', color: 'var(--color-text-secondary)', marginTop: '4px', display: 'flex', gap: '12px' }}>
                    {item.pub_date && <span>{item.pub_date}</span>}
                    {item.source && <span>来源: {item.source.length > 30 ? item.source.substring(0, 30) + '...' : item.source}</span>}
                    {item.keyword_score != null && <span style={{ color: '#059669' }}>关键词匹配: {item.keyword_score}</span>}
                    {item.relevance_score != null && <span style={{ color: '#475569' }}>AI相关性: {(item.relevance_score * 100).toFixed(0)}%</span>}
                  </div>
                  {item.content && (
                    <div style={{ fontSize: '12px', color: 'var(--color-text-secondary)', marginTop: '6px', lineHeight: '1.6', maxHeight: '60px', overflow: 'hidden' }}>
                      {item.content.substring(0, 200)}...
                    </div>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );

  // ============================================================
  // 渲染: 智能推荐 tab (新增)
  // ============================================================
  const renderRecommendTab = () => (
    <div>
      {/* 聚合错误提示 */}
      {aggregateErrors.length > 0 && (
        <div style={{ marginBottom: '16px', padding: '12px 16px', background: '#fffbeb', border: '1px solid #fbbf24', borderRadius: '8px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px', fontSize: '13px', fontWeight: 600, color: '#92400e' }}>
            <AlertTriangle size={14} /> 以下数据源抓取异常 ({aggregateErrors.length} 个)
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', maxHeight: '120px', overflowY: 'auto' }}>
            {aggregateErrors.map((e, i) => (
              <div key={i} style={{ fontSize: '12px', color: '#78350f', display: 'flex', gap: '6px', alignItems: 'flex-start' }}>
                <span style={{ color: '#dc2626', flexShrink: 0 }}>✗</span>
                <span><b>{e.code || '未知源'}</b>: {e.error}</span>
              </div>
            ))}
          </div>
          <div style={{ marginTop: '8px', fontSize: '11px', color: '#92400e' }}>
            提示: 可在"数据源管理"中更换地址或禁用失效源
          </div>
        </div>
      )}
      {/* 顶部统计卡 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '12px', marginBottom: '20px' }}>
        <div style={{ padding: '16px', background: 'linear-gradient(135deg, #eff6ff, #dbeafe)', borderRadius: '12px', border: '1px solid #bfdbfe' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '8px' }}>
            <Sparkles size={18} color="#1a56db" />
            <span style={{ fontSize: '13px', color: '#1e3a8a', fontWeight: 500 }}>智能商机库</span>
          </div>
          <div style={{ fontSize: '32px', fontWeight: 700, color: '#1a56db' }}>{hotspotsTotal}</div>
          <div style={{ fontSize: '11px', color: '#1d4ed8', marginTop: '2px' }}>去重+评分后的聚合商机</div>
        </div>
        <div style={{ padding: '16px', background: 'linear-gradient(135deg, #fef2f2, #fee2e2)', borderRadius: '12px', border: '1px solid #fecaca' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '8px' }}>
            <Flame size={18} color="#dc2626" />
            <span style={{ fontSize: '13px', color: '#991b1b', fontWeight: 500 }}>高分热点</span>
          </div>
          <div style={{ fontSize: '32px', fontWeight: 700, color: '#dc2626' }}>{hotspots.filter(h => h.is_hot).length}</div>
          <div style={{ fontSize: '11px', color: '#b91c1c', marginTop: '2px' }}>评分 ≥ 60 的优质商机</div>
        </div>
        <div style={{ padding: '16px', background: 'linear-gradient(135deg, #eff6ff, #dbeafe)', borderRadius: '12px', border: '1px solid #bfdbfe' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '8px' }}>
            <Rocket size={18} color="#2563eb" />
            <span style={{ fontSize: '13px', color: '#1e40af', fontWeight: 500 }}>已转标书</span>
          </div>
          <div style={{ fontSize: '32px', fontWeight: 700, color: '#2563eb' }}>{hotspots.filter(h => h.is_converted).length}</div>
          <div style={{ fontSize: '11px', color: '#1d4ed8', marginTop: '2px' }}>已转为投标项目</div>
        </div>
        <div style={{ padding: '16px', background: 'linear-gradient(135deg, #f0fdf4, #dcfce7)', borderRadius: '12px', border: '1px solid #bbf7d0' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '8px' }}>
            <Database size={18} color="#16a34a" />
            <span style={{ fontSize: '13px', color: '#166534', fontWeight: 500 }}>可用源</span>
          </div>
          <div style={{ fontSize: '32px', fontWeight: 700, color: '#16a34a' }}>{sources.filter(s => s.enabled).length}/{sources.length}</div>
          <div style={{ fontSize: '11px', color: '#15803d', marginTop: '2px' }}>已启用 / 总数据源</div>
        </div>
      </div>

      {/* 顶部操作栏 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px', flexWrap: 'wrap', gap: '8px' }}>
        <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
          <select
            value={hotspotFilter.industry_code}
            onChange={(e) => setHotspotFilter({ ...hotspotFilter, industry_code: e.target.value })}
            style={{ padding: '6px 12px', border: '1px solid var(--color-border)', borderRadius: '6px', fontSize: '12px', background: 'white' }}
          >
            <option value="all">全部行业</option>
            {industries.map(cat => (
              <optgroup key={cat.code} label={`${cat.icon} ${cat.name}`}>
                <option value={cat.code}>{cat.name}(全部)</option>
                {(cat.children || []).map(sub => (
                  <option key={sub.code} value={sub.code}>{sub.name}</option>
                ))}
              </optgroup>
            ))}
          </select>
          <input
            type="text"
            value={hotspotFilter.keyword}
            onChange={(e) => setHotspotFilter({ ...hotspotFilter, keyword: e.target.value })}
            placeholder="关键词搜索"
            style={{ padding: '6px 12px', border: '1px solid var(--color-border)', borderRadius: '6px', fontSize: '12px' }}
          />
          <select
            value={hotspotFilter.is_hot === undefined ? 'all' : hotspotFilter.is_hot ? 'hot' : 'normal'}
            onChange={(e) => setHotspotFilter({ ...hotspotFilter, is_hot: e.target.value === 'all' ? undefined : e.target.value === 'hot' })}
            style={{ padding: '6px 12px', border: '1px solid var(--color-border)', borderRadius: '6px', fontSize: '12px', background: 'white' }}
          >
            <option value="all">全部</option>
            <option value="hot">仅热点</option>
            <option value="normal">非热点</option>
          </select>
        </div>
        <div style={{ display: 'flex', gap: '6px' }}>
          <button
            onClick={loadHotspots}
            style={{ padding: '6px 12px', background: 'var(--color-surface)', border: '1px solid var(--color-border)', borderRadius: '6px', cursor: 'pointer', fontSize: '12px', display: 'flex', alignItems: 'center', gap: '4px' }}
          >
            <RefreshCw size={12} /> 刷新
          </button>
          <button
            onClick={handleAggregate}
            disabled={aggregating}
            style={{ padding: '6px 14px', background: aggregating ? '#94a3b8' : 'linear-gradient(135deg, #1a56db, #1e40af)', color: 'white', border: 'none', borderRadius: '6px', cursor: aggregating ? 'not-allowed' : 'pointer', fontSize: '12px', display: 'flex', alignItems: 'center', gap: '4px' }}
          >
            {aggregating ? <Loader2 size={12} style={{ animation: 'spin 1s linear infinite' }} /> : <Zap size={12} />} {aggregating ? '聚合中...' : '立即聚合抓取'}
          </button>
        </div>
      </div>

      {/* 商机列表 */}
      {hotspotsLoading ? (
        <div style={{ textAlign: 'center', padding: '40px', color: 'var(--color-text-secondary)' }}>
          <Loader2 size={24} style={{ animation: 'spin 1s linear infinite' }} />
          <div style={{ marginTop: '8px', fontSize: '13px' }}>加载中...</div>
        </div>
      ) : hotspots.length === 0 ? (
        <div style={{ textAlign: 'center', padding: '60px', color: 'var(--color-text-secondary)', background: 'var(--color-surface)', borderRadius: '12px', border: '1px solid var(--color-border)' }}>
          <Sparkles size={48} color="#cbd5e1" style={{ margin: '0 auto 12px' }} />
          <div style={{ fontSize: '14px', fontWeight: 500, marginBottom: '4px' }}>暂无聚合商机</div>
          <div style={{ fontSize: '12px', marginBottom: '16px' }}>点击"立即聚合抓取"从所有启用的数据源采集并评分</div>
          <button
            onClick={handleAggregate}
            disabled={aggregating}
            style={{ padding: '8px 20px', background: 'linear-gradient(135deg, #1a56db, #1e40af)', color: 'white', border: 'none', borderRadius: '6px', cursor: 'pointer', fontSize: '13px' }}
          >
            {aggregating ? '采集中...' : '开始首次采集'}
          </button>
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          {hotspots.map((h, idx) => (
            <div
              key={h.id}
              style={{
                padding: '14px 16px',
                background: 'var(--color-surface)',
                border: '1px solid var(--color-border)',
                borderRadius: '10px',
                borderLeft: h.is_hot ? '3px solid #dc2626' : '3px solid #cbd5e1',
                opacity: h.is_converted ? 0.7 : 1,
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '12px' }}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '4px', flexWrap: 'wrap' }}>
                    <span style={{ fontSize: '12px', color: 'var(--color-text-secondary)', minWidth: '24px' }}>#{idx + 1}</span>
                    {h.is_hot && (
                      <span style={{ padding: '2px 8px', borderRadius: '10px', fontSize: '10px', background: '#fef2f2', color: '#dc2626', fontWeight: 600, display: 'inline-flex', alignItems: 'center', gap: '3px' }}>
                        <Flame size={9} /> 高分
                      </span>
                    )}
                    {h.industry_code && (
                      <span style={{ padding: '2px 8px', borderRadius: '10px', fontSize: '10px', background: '#f0f9ff', color: '#0369a1', fontWeight: 500 }}>
                        {getIndustryDisplayName(h.industry_code)}
                      </span>
                    )}
                    {h.is_converted && (
                      <span style={{ padding: '2px 8px', borderRadius: '10px', fontSize: '10px', background: '#dcfce7', color: '#16a34a', fontWeight: 600, display: 'inline-flex', alignItems: 'center', gap: '3px' }}>
                        <Check size={9} /> 已转项目
                      </span>
                    )}
                  </div>
                  <a href={h.url} target="_blank" rel="noopener noreferrer" style={{ fontSize: '14px', fontWeight: 500, color: 'var(--color-text)', textDecoration: 'none', display: 'block', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {h.title}
                  </a>
                  <div style={{ fontSize: '11px', color: 'var(--color-text-secondary)', marginTop: '6px', display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
                    {h.region && <span style={{ display: 'flex', alignItems: 'center', gap: '3px' }}><MapPin size={10} /> {h.region}</span>}
                    {h.amount > 0 && <span style={{ display: 'flex', alignItems: 'center', gap: '3px' }}><DollarSign size={10} /> {formatAmount(h.amount)}</span>}
                    {h.owner_org && <span style={{ display: 'flex', alignItems: 'center', gap: '3px' }}><Building2 size={10} /> {h.owner_org.slice(0, 15)}</span>}
                    {h.pub_date && <span style={{ display: 'flex', alignItems: 'center', gap: '3px' }}><Clock size={10} /> {h.pub_date}</span>}
                    {h.sources && h.sources.length > 1 && <span style={{ color: '#1a56db' }}>🔗 {h.sources.length} 源合并</span>}
                  </div>
                  <div style={{ display: 'flex', gap: '6px', marginTop: '8px', flexWrap: 'wrap' }}>
                    <button
                      onClick={() => handleViewDetail(h.id)}
                      style={{ padding: '3px 10px', background: 'var(--color-surface)', border: '1px solid var(--color-border)', borderRadius: '4px', cursor: 'pointer', fontSize: '11px', display: 'flex', alignItems: 'center', gap: '3px' }}
                    >
                      <FileText size={10} /> 查看详情
                    </button>
                    <button
                      onClick={() => handleViewScore(h.id)}
                      style={{ padding: '3px 10px', background: 'var(--color-surface)', border: '1px solid var(--color-border)', borderRadius: '4px', cursor: 'pointer', fontSize: '11px', display: 'flex', alignItems: 'center', gap: '3px' }}
                    >
                      <BarChart3 size={10} /> 评分细项
                    </button>
                    {!h.is_converted && (
                      <button
                        onClick={() => handleConvertToBid(h.id)}
                        disabled={converting === h.id}
                        style={{ padding: '3px 10px', background: converting === h.id ? '#94a3b8' : 'linear-gradient(135deg, #059669, #10b981)', color: 'white', border: 'none', borderRadius: '4px', cursor: converting === h.id ? 'not-allowed' : 'pointer', fontSize: '11px', display: 'flex', alignItems: 'center', gap: '3px' }}
                      >
                        {converting === h.id ? <Loader2 size={10} style={{ animation: 'spin 1s linear infinite' }} /> : <Rocket size={10} />} 一键转标书
                      </button>
                    )}
                    <a href={h.url} target="_blank" rel="noopener noreferrer" style={{ padding: '3px 10px', background: 'var(--color-surface)', border: '1px solid var(--color-border)', borderRadius: '4px', fontSize: '11px', textDecoration: 'none', color: 'var(--color-text)', display: 'inline-flex', alignItems: 'center', gap: '3px' }}>
                      <ExternalLink size={10} /> 原文
                    </a>
                  </div>
                </div>
                <div style={{ flexShrink: 0, textAlign: 'center', minWidth: '64px' }}>
                  <div style={{ fontSize: '22px', fontWeight: 700, color: getScoreColor(h.score_total) }}>
                    {h.score_total.toFixed(0)}
                  </div>
                  <div style={{ fontSize: '10px', color: 'var(--color-text-secondary)' }}>综合分</div>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {scoreDetail && renderScoreModal()}
      {hotspotDetail && renderDetailModal()}
      {detailLoading && !hotspotDetail && (
        <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, background: 'rgba(0,0,0,0.4)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000 }}>
          <div style={{ background: 'white', padding: '24px 32px', borderRadius: '12px', display: 'flex', alignItems: 'center', gap: '10px' }}>
            <Loader2 size={20} style={{ animation: 'spin 1s linear infinite', color: '#1a56db' }} />
            <span style={{ fontSize: '13px', color: 'var(--color-text)' }}>正在加载详情...</span>
          </div>
        </div>
      )}
    </div>
  );

  // ============================================================
  // 渲染: 评分详情弹窗
  // ============================================================
  const renderScoreModal = () => {
    if (!scoreDetail) return null;
    const s = scoreDetail.score;
    const dimensions = [
      { key: 'urgency', label: '紧急度', value: s.urgency, max: 20, color: '#dc2626', desc: '距截止日期' },
      { key: 'match', label: '匹配度', value: s.match, max: 30, color: '#1a56db', desc: '行业/关键词' },
      { key: 'amount', label: '金额合理性', value: s.amount, max: 20, color: '#059669', desc: '公司偏好' },
      { key: 'region', label: '地域偏好', value: s.region, max: 15, color: '#0891b2', desc: '地域权重' },
      { key: 'freshness', label: '时效性', value: s.freshness, max: 15, color: '#d97706', desc: '发布时间' },
    ];
    return (
      <div
        onClick={() => setScoreDetail(null)}
        style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, background: 'rgba(0,0,0,0.5)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000 }}
      >
        <div onClick={(e) => e.stopPropagation()} style={{ background: 'white', borderRadius: '12px', padding: '24px', maxWidth: '480px', width: '90%', maxHeight: '80vh', overflowY: 'auto' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '16px' }}>
            <div>
              <div style={{ fontSize: '16px', fontWeight: 600 }}>{scoreDetail.industry_icon} 5 维评分细项</div>
              <div style={{ fontSize: '12px', color: 'var(--color-text-secondary)', marginTop: '4px' }}>{scoreDetail.title}</div>
            </div>
            <button onClick={() => setScoreDetail(null)} style={{ background: 'transparent', border: 'none', cursor: 'pointer', color: 'var(--color-text-secondary)' }}>
              <X size={18} />
            </button>
          </div>
          <div style={{ textAlign: 'center', padding: '16px', background: 'linear-gradient(135deg, #eff6ff, #dbeafe)', borderRadius: '10px', marginBottom: '16px' }}>
            <div style={{ fontSize: '11px', color: '#1a56db', fontWeight: 500 }}>综合价值评分</div>
            <div style={{ fontSize: '40px', fontWeight: 700, color: getScoreColor(s.total) }}>{s.total.toFixed(1)}</div>
            <div style={{ fontSize: '11px', color: 'var(--color-text-secondary)' }}>满分 100</div>
          </div>
          {dimensions.map(d => (
            <div key={d.key} style={{ marginBottom: '10px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '12px', marginBottom: '4px' }}>
                <span><span style={{ color: d.color, fontWeight: 600 }}>{d.label}</span> <span style={{ color: 'var(--color-text-secondary)' }}>({d.desc})</span></span>
                <span style={{ fontWeight: 600 }}>{d.value.toFixed(1)} / {d.max}</span>
              </div>
              <div style={{ height: '8px', background: '#f1f5f9', borderRadius: '4px', overflow: 'hidden' }}>
                <div style={{ width: `${(d.value / d.max) * 100}%`, height: '100%', background: d.color, borderRadius: '4px' }} />
              </div>
            </div>
          ))}
        </div>
      </div>
    );
  };

  // ============================================================
  // 渲染: 热点详情弹窗 (原文 + 关键字段 + 评分摘要)
  // ============================================================
  const renderDetailModal = () => {
    if (!hotspotDetail) return null;
    const d = hotspotDetail;
    const summary = d.content && d.content.length > 600 ? d.content.slice(0, 600) + '…' : d.content;

    return (
      <div
        onClick={() => setHotspotDetail(null)}
        style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, background: 'rgba(0,0,0,0.5)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000, padding: '20px' }}
      >
        <div onClick={(e) => e.stopPropagation()} style={{ background: 'white', borderRadius: '12px', padding: '24px', maxWidth: '720px', width: '100%', maxHeight: '85vh', overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
          {/* Header */}
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '14px', gap: '12px' }}>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '6px', flexWrap: 'wrap' }}>
                <span style={{ padding: '2px 8px', borderRadius: '10px', fontSize: '10px', background: '#f0f9ff', color: '#0369a1', fontWeight: 500 }}>
                  {d.industry_icon} {d.industry_name}
                </span>
                {d.is_hot && <span style={{ padding: '2px 8px', borderRadius: '10px', fontSize: '10px', background: '#fef2f2', color: '#dc2626', fontWeight: 600 }}>🔥 高分</span>}
                {d.is_converted && <span style={{ padding: '2px 8px', borderRadius: '10px', fontSize: '10px', background: '#dcfce7', color: '#16a34a', fontWeight: 600 }}>已转项目</span>}
                <span style={{ padding: '2px 8px', borderRadius: '10px', fontSize: '10px', background: '#eff6ff', color: '#1a56db', fontWeight: 600 }}>综合分 {d.score.total.toFixed(1)}</span>
              </div>
              <div style={{ fontSize: '16px', fontWeight: 600, color: 'var(--color-text)', lineHeight: 1.5 }}>{d.title}</div>
            </div>
            <button onClick={() => setHotspotDetail(null)} style={{ background: 'transparent', border: 'none', cursor: 'pointer', color: 'var(--color-text-secondary)', flexShrink: 0 }}>
              <X size={18} />
            </button>
          </div>

          {/* Meta 信息条 */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: '8px', padding: '10px 12px', background: 'var(--color-surface)', borderRadius: '8px', marginBottom: '12px' }}>
            {d.source && (
              <div style={{ fontSize: '11px' }}>
                <div style={{ color: 'var(--color-text-secondary)' }}>来源</div>
                <div style={{ color: 'var(--color-text)', fontWeight: 500, marginTop: '2px' }}>{d.source}</div>
              </div>
            )}
            {d.region && (
              <div style={{ fontSize: '11px' }}>
                <div style={{ color: 'var(--color-text-secondary)' }}>地域</div>
                <div style={{ color: 'var(--color-text)', fontWeight: 500, marginTop: '2px' }}>{d.region}</div>
              </div>
            )}
            {d.amount > 0 && (
              <div style={{ fontSize: '11px' }}>
                <div style={{ color: 'var(--color-text-secondary)' }}>金额</div>
                <div style={{ color: 'var(--color-text)', fontWeight: 500, marginTop: '2px' }}>{formatAmount(d.amount)}</div>
              </div>
            )}
            {d.bid_deadline && (
              <div style={{ fontSize: '11px' }}>
                <div style={{ color: 'var(--color-text-secondary)' }}>截止</div>
                <div style={{ color: 'var(--color-text)', fontWeight: 500, marginTop: '2px' }}>{d.bid_deadline}</div>
              </div>
            )}
            {d.owner_org && (
              <div style={{ fontSize: '11px' }}>
                <div style={{ color: 'var(--color-text-secondary)' }}>业主</div>
                <div style={{ color: 'var(--color-text)', fontWeight: 500, marginTop: '2px' }}>{d.owner_org}</div>
              </div>
            )}
            {d.pub_date && (
              <div style={{ fontSize: '11px' }}>
                <div style={{ color: 'var(--color-text-secondary)' }}>发布日期</div>
                <div style={{ color: 'var(--color-text)', fontWeight: 500, marginTop: '2px' }}>{d.pub_date}</div>
              </div>
            )}
            {d.sources && d.sources.length > 1 && (
              <div style={{ fontSize: '11px' }}>
                <div style={{ color: 'var(--color-text-secondary)' }}>多源合并</div>
                <div style={{ color: '#1a56db', fontWeight: 500, marginTop: '2px' }}>🔗 {d.sources.length} 源</div>
              </div>
            )}
          </div>

          {/* 评分 5 维进度条 */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: '6px', marginBottom: '12px' }}>
            {[
              { k: '紧急度', v: d.score.urgency, max: 20, c: '#dc2626' },
              { k: '匹配度', v: d.score.match, max: 30, c: '#1a56db' },
              { k: '金额', v: d.score.amount, max: 20, c: '#059669' },
              { k: '地域', v: d.score.region, max: 15, c: '#0891b2' },
              { k: '时效', v: d.score.freshness, max: 15, c: '#d97706' },
            ].map(item => (
              <div key={item.k} style={{ textAlign: 'center' }}>
                <div style={{ fontSize: '10px', color: 'var(--color-text-secondary)' }}>{item.k}</div>
                <div style={{ fontSize: '14px', fontWeight: 600, color: item.c }}>{item.v.toFixed(0)}</div>
                <div style={{ height: '3px', background: '#f1f5f9', borderRadius: '2px', marginTop: '2px' }}>
                  <div style={{ width: `${(item.v / item.max) * 100}%`, height: '100%', background: item.c, borderRadius: '2px' }} />
                </div>
              </div>
            ))}
          </div>

          {/* 详情正文 */}
          <div style={{ fontSize: '12px', fontWeight: 600, color: 'var(--color-text)', marginBottom: '6px', display: 'flex', alignItems: 'center', gap: '4px' }}>
            <FileText size={12} /> 详情正文
            {d.content_length > 0 && <span style={{ fontSize: '10px', color: 'var(--color-text-secondary)', fontWeight: 400 }}>({d.content_length} 字符)</span>}
          </div>
          <div style={{ flex: 1, overflowY: 'auto', padding: '12px 14px', background: 'var(--color-surface)', borderRadius: '8px', border: '1px solid var(--color-border)', fontSize: '13px', lineHeight: 1.7, color: 'var(--color-text)', whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
            {d.content ? summary : <span style={{ color: 'var(--color-text-secondary)', fontStyle: 'italic' }}>暂无详情正文。可点击"原文"访问外链,或重新采集详情。</span>}
          </div>

          {/* Footer Actions */}
          <div style={{ display: 'flex', gap: '8px', marginTop: '12px', flexWrap: 'wrap' }}>
            <a href={d.url} target="_blank" rel="noopener noreferrer" style={{ padding: '6px 12px', background: 'linear-gradient(135deg, #1a56db, #1e40af)', color: 'white', borderRadius: '6px', fontSize: '12px', textDecoration: 'none', display: 'inline-flex', alignItems: 'center', gap: '4px' }}>
              <Globe size={12} /> 访问原文
            </a>
            <button
              onClick={() => {
                if (d.content) {
                  navigator.clipboard.writeText(d.content).then(() => showToast('success', '已复制详情到剪贴板'));
                }
              }}
              style={{ padding: '6px 12px', background: 'var(--color-surface)', border: '1px solid var(--color-border)', borderRadius: '6px', cursor: 'pointer', fontSize: '12px', display: 'flex', alignItems: 'center', gap: '4px' }}
            >
              <Copy size={12} /> 复制正文
            </button>
            {d.converted_project && (
              <div style={{ padding: '6px 12px', background: '#dcfce7', color: '#16a34a', borderRadius: '6px', fontSize: '12px', display: 'inline-flex', alignItems: 'center', gap: '4px' }}>
                ✅ 已关联项目: {d.converted_project.name}
              </div>
            )}
          </div>
        </div>
      </div>
    );
  };

  // ============================================================
  // 渲染: 数据源 tab (新增)
  // ============================================================
  const renderSourcesTab = () => (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px', flexWrap: 'wrap', gap: '8px' }}>
        <div>
          <h3 style={{ fontSize: '16px', fontWeight: 600 }}>数据源管理</h3>
          <p style={{ fontSize: '12px', color: 'var(--color-text-secondary)', marginTop: '2px' }}>浏览、启用/禁用预置数据源,支持按行业筛选</p>
        </div>
        <div style={{ display: 'flex', gap: '6px' }}>
          <select
            value={sourcesFilter}
            onChange={(e) => { setSourcesFilter(e.target.value); setTimeout(loadSources, 0); }}
            style={{ padding: '6px 12px', border: '1px solid var(--color-border)', borderRadius: '6px', fontSize: '12px', background: 'white' }}
          >
            <option value="all">全部行业</option>
            {industries.map(cat => (
              <option key={cat.code} value={cat.code}>{cat.icon} {cat.name}</option>
            ))}
          </select>
          <button
            onClick={handleSyncSources}
            disabled={syncing}
            style={{ padding: '6px 14px', background: syncing ? '#94a3b8' : 'linear-gradient(135deg, #0891b2, #0e7490)', color: 'white', border: 'none', borderRadius: '6px', cursor: syncing ? 'not-allowed' : 'pointer', fontSize: '12px', display: 'flex', alignItems: 'center', gap: '4px' }}
          >
            {syncing ? <Loader2 size={12} style={{ animation: 'spin 1s linear infinite' }} /> : <RefreshCw size={12} />} {syncing ? '同步中...' : '从YAML同步'}
          </button>
        </div>
      </div>

      {sourcesLoading ? (
        <div style={{ textAlign: 'center', padding: '40px', color: 'var(--color-text-secondary)' }}>
          <Loader2 size={24} style={{ animation: 'spin 1s linear infinite' }} />
        </div>
      ) : sources.length === 0 ? (
        <div style={{ textAlign: 'center', padding: '60px', color: 'var(--color-text-secondary)', background: 'var(--color-surface)', borderRadius: '12px', border: '1px solid var(--color-border)' }}>
          <Database size={48} color="#cbd5e1" style={{ margin: '0 auto 12px' }} />
          <div style={{ fontSize: '14px', fontWeight: 500, marginBottom: '4px' }}>该行业下暂无数据源</div>
          <div style={{ fontSize: '12px' }}>点击"从YAML同步"加载预置数据源</div>
        </div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: '12px' }}>
          {sources.map(src => (
            <div
              key={src.code}
              style={{
                padding: '16px',
                background: 'var(--color-surface)',
                border: `1px solid ${src.enabled ? '#bfdbfe' : 'var(--color-border)'}`,
                borderRadius: '10px',
                opacity: src.enabled ? 1 : 0.6,
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '8px' }}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: '14px', fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{src.name}</div>
                  <div style={{ fontSize: '11px', color: 'var(--color-text-secondary)', marginTop: '2px' }}>code: {src.code}</div>
                </div>
                <span style={{ padding: '2px 8px', borderRadius: '4px', fontSize: '10px', background: src.type === 'rss' ? '#dbeafe' : src.type === 'api' ? '#fef3c7' : '#e2e8f0', color: src.type === 'rss' ? '#1e40af' : src.type === 'api' ? '#92400e' : '#475569', fontWeight: 600, marginLeft: '8px', flexShrink: 0 }}>
                  {src.type.toUpperCase()}
                </span>
              </div>
              {src.description && <div style={{ fontSize: '12px', color: 'var(--color-text-secondary)', marginBottom: '8px', lineHeight: 1.5 }}>{src.description}</div>}
              <div style={{ display: 'flex', gap: '6px', marginBottom: '10px', fontSize: '11px', color: 'var(--color-text-secondary)' }}>
                <span>行业: {getIndustryDisplayName(src.industry_code)}</span>
                <span>·</span>
                <span>权重: {src.weight}</span>
                {src.last_status && <><span>·</span><span style={{ color: src.last_status === 'success' ? '#059669' : '#dc2626' }}>{src.last_status}</span></>}
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <a href={src.url} target="_blank" rel="noopener noreferrer" style={{ fontSize: '11px', color: '#2563eb', textDecoration: 'none', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '180px' }}>
                  {src.url}
                </a>
                <button
                  onClick={() => handleToggleSource(src)}
                  style={{
                    padding: '3px 12px',
                    background: src.enabled ? '#fef2f2' : '#ecfdf5',
                    color: src.enabled ? '#dc2626' : '#059669',
                    border: 'none',
                    borderRadius: '4px',
                    cursor: 'pointer',
                    fontSize: '11px',
                    fontWeight: 600,
                    display: 'flex',
                    alignItems: 'center',
                    gap: '3px',
                  }}
                >
                  {src.enabled ? <X size={10} /> : <Check size={10} />} {src.enabled ? '禁用' : '启用'}
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* 行业快捷聚合 */}
      <div style={{ marginTop: '24px', padding: '20px', background: 'linear-gradient(135deg, #eff6ff, #eff6ff)', borderRadius: '12px', border: '1px solid #bfdbfe' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '12px' }}>
          <Zap size={16} color="#1a56db" />
          <span style={{ fontSize: '14px', fontWeight: 600, color: '#1e3a8a' }}>按行业快捷聚合</span>
          <span style={{ fontSize: '11px', color: '#1a56db' }}>点击行业卡片,即时从该行业所有源抓取</span>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6, 1fr)', gap: '8px' }}>
          {industries.map(cat => (
            <button
              key={cat.code}
              onClick={() => handleAggregateIndustry(cat.code)}
              disabled={aggregating}
              style={{
                padding: '12px 8px',
                background: 'white',
                border: '1px solid #bfdbfe',
                borderRadius: '8px',
                cursor: aggregating ? 'not-allowed' : 'pointer',
                textAlign: 'center',
                fontSize: '12px',
                opacity: aggregating ? 0.5 : 1,
              }}
            >
              <div style={{ fontSize: '20px', marginBottom: '4px' }}>{cat.icon}</div>
              <div style={{ fontWeight: 500 }}>{cat.name}</div>
            </button>
          ))}
        </div>
      </div>
    </div>
  );

  // ============================================================
  // 主渲染
  // ============================================================
  return (
    <div>
      <div style={{ marginBottom: '32px' }}>
        <h2 style={{ fontSize: '24px', fontWeight: 700 }}>资讯中心</h2>
        <p style={{ fontSize: '14px', color: 'var(--color-text-secondary)', marginTop: '4px' }}>
          智能商机推荐、多源聚合抓取、5维价值评分、一键转标书
        </p>
      </div>

      <div style={{ display: 'flex', gap: '8px', marginBottom: '20px', flexWrap: 'wrap' }}>
        {([
          { key: 'recommend' as NewsTab, label: '智能推荐', icon: <Sparkles size={14} />, badge: hotspots.filter(h => h.is_hot).length },
          { key: 'sources' as NewsTab, label: '数据源', icon: <Database size={14} />, badge: sources.filter(s => s.enabled).length },
          { key: 'today-hot' as NewsTab, label: '今日热点/商机', icon: <TrendingUp size={14} /> },
          { key: 'tasks' as NewsTab, label: '监控任务', icon: <Bell size={14} /> },
          { key: 'results' as NewsTab, label: `采集结果 (${newsResults.length})`, icon: <Newspaper size={14} /> },
        ]).map(tab => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            style={{
              padding: '8px 16px',
              background: activeTab === tab.key ? 'var(--color-primary)' : 'var(--color-surface)',
              color: activeTab === tab.key ? 'white' : 'var(--color-text)',
              border: `1px solid ${activeTab === tab.key ? 'var(--color-primary)' : 'var(--color-border)'}`,
              borderRadius: '8px',
              cursor: 'pointer',
              fontSize: '13px',
              fontWeight: 500,
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
            }}
          >
            {tab.icon} {tab.label}
            {tab.badge !== undefined && tab.badge > 0 && (
              <span style={{ padding: '0 6px', background: activeTab === tab.key ? 'rgba(255,255,255,0.25)' : '#fef2f2', color: activeTab === tab.key ? 'white' : '#dc2626', borderRadius: '8px', fontSize: '10px', fontWeight: 600, minWidth: '16px', textAlign: 'center' }}>
                {tab.badge}
              </span>
            )}
          </button>
        ))}
      </div>

      {activeTab === 'recommend' && renderRecommendTab()}
      {activeTab === 'sources' && renderSourcesTab()}
      {activeTab === 'today-hot' && renderTodayHotTab()}
      {activeTab === 'tasks' && renderTasksTab()}
      {activeTab === 'results' && renderResultsTab()}

      {error && (
        <div style={{ marginTop: '16px', padding: '12px', background: '#fef2f2', borderRadius: '8px', color: '#dc2626', fontSize: '13px' }}>{error}</div>
      )}

      {toast && (
        <div
          style={{
            position: 'fixed',
            top: '24px',
            right: '24px',
            padding: '12px 20px',
            background: toast.type === 'success' ? '#ecfdf5' : toast.type === 'warning' ? '#fffbeb' : '#fef2f2',
            color: toast.type === 'success' ? '#059669' : toast.type === 'warning' ? '#92400e' : '#dc2626',
            border: `1px solid ${toast.type === 'success' ? '#a7f3d0' : toast.type === 'warning' ? '#fbbf24' : '#fecaca'}`,
            borderRadius: '8px',
            fontSize: '13px',
            zIndex: 9999,
            boxShadow: '0 4px 12px rgba(0,0,0,0.08)',
          }}
        >
          {toast.text}
        </div>
      )}
    </div>
  );
}
