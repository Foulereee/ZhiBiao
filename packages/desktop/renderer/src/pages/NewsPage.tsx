import { useState, useEffect } from 'react';
import { Newspaper, Plus, Trash2, Play, Loader2, RefreshCw, Filter, Bell, TrendingUp, Flame, Briefcase, Clock, ExternalLink, Zap } from 'lucide-react';
import { newsApi } from '../services/api';

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

type NewsTab = 'tasks' | 'results' | 'today-hot';
type HotCategory = 'all' | 'hot' | 'business';

export default function NewsPage() {
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
  const [activeTab, setActiveTab] = useState<NewsTab>('today-hot');

  const [hotItems, setHotItems] = useState<HotItem[]>([]);
  const [hotCategory, setHotCategory] = useState<HotCategory>('all');
  const [hotLoading, setHotLoading] = useState(false);
  const [hotRefreshing, setHotRefreshing] = useState(false);
  const [hotStats, setHotStats] = useState({ total: 0, hot_count: 0, business_count: 0, date: '' });

  useEffect(() => {
    loadTasks();
    loadTodayHot();
  }, []);

  useEffect(() => {
    loadTodayHot();
  }, [hotCategory]);

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
    try {
      const res = await newsApi.runTask(taskId);
      if (res.data.success) {
        const data = res.data.data || {};
        const results = data.results || data.filtered || [];
        setNewsResults(results);
        setActiveTab('results');
      } else {
        setError(res.data.error || '执行失败');
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

  const renderTasksTab = () => (
    <div style={{ background: 'var(--color-surface)', borderRadius: '12px', padding: '24px', border: '1px solid var(--color-border)' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
        <h3 style={{ fontSize: '16px', fontWeight: 600 }}>监控任务</h3>
        <div style={{ display: 'flex', gap: '8px' }}>
          <button onClick={loadTasks} style={{ padding: '6px 10px', background: 'var(--color-surface)', border: '1px solid var(--color-border)', borderRadius: '6px', cursor: 'pointer' }}>
            <RefreshCw size={14} />
          </button>
          <button
            onClick={() => setShowAdd(true)}
            style={{ padding: '6px 14px', background: 'var(--color-primary)', color: 'white', border: 'none', borderRadius: '6px', cursor: 'pointer', fontSize: '13px', display: 'flex', alignItems: 'center', gap: '4px' }}
          >
            <Plus size={14} /> 新建监控
          </button>
        </div>
      </div>

      {showAdd && (
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

      {tasks.length === 0 ? (
        <p style={{ color: 'var(--color-text-secondary)', textAlign: 'center', padding: '24px', fontSize: '14px' }}>暂无监控任务，点击"新建监控"开始</p>
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

  const renderResultsTab = () => (
    <div style={{ background: 'var(--color-surface)', borderRadius: '12px', padding: '24px', border: '1px solid var(--color-border)' }}>
      <h3 style={{ fontSize: '16px', fontWeight: 600, marginBottom: '16px' }}>采集结果 ({newsResults.length})</h3>
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

  return (
    <div>
      <div style={{ marginBottom: '32px' }}>
        <h2 style={{ fontSize: '24px', fontWeight: 700 }}>资讯中心</h2>
        <p style={{ fontSize: '14px', color: 'var(--color-text-secondary)', marginTop: '4px' }}>
          今日热点/商机、招标信息多源采集、AI智能过滤、语义筛选
        </p>
      </div>

      <div style={{ display: 'flex', gap: '8px', marginBottom: '20px' }}>
        {([
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
          </button>
        ))}
      </div>

      {activeTab === 'today-hot' && renderTodayHotTab()}
      {activeTab === 'tasks' && renderTasksTab()}
      {activeTab === 'results' && renderResultsTab()}

      {error && (
        <div style={{ marginTop: '16px', padding: '12px', background: '#fef2f2', borderRadius: '8px', color: '#dc2626', fontSize: '13px' }}>{error}</div>
      )}
    </div>
  );
}
