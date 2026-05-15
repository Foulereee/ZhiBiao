import { useState, useRef, useEffect, useCallback } from 'react';
import { FileText, Upload, CheckCircle, AlertTriangle, Download, Settings, Eye, Wand2, Palette, Save, Plus, Trash2, RotateCcw, ChevronDown, ChevronRight, Copy } from 'lucide-react';
import { formatApi } from '../services/api';
import StepHeader from '../components/common/StepHeader';

type FormatMode = 'format' | 'check' | 'diff' | 'beautify';
type PageTab = 'format' | 'config';

interface FormatIssue {
  type: string;
  expected: string;
  actual: string;
  text_preview?: string;
  label?: string;
  detail?: string;
}

interface FormatDiff {
  location: string;
  property: string;
  expected: string;
  actual: string;
  label: string;
}

interface ConfigGroup {
  key: string;
  label: string;
  fields: ConfigField[];
}

interface ConfigField {
  key: string;
  label: string;
  type: 'text' | 'number' | 'select' | 'checkbox';
  options?: string[];
  optionLabels?: Record<string, string>;
  step?: number;
  min?: number;
  max?: number;
  unit?: string;
}

const FONT_OPTIONS = [
  '方正小标宋简体', '黑体', '宋体', '仿宋_GB2312', '楷体_GB2312',
  '华文中宋', '华文楷体', '华文仿宋', '微软雅黑', '等线',
  'Times New Roman', 'Arial', 'Calibri', 'Cambria',
];

const ALIGN_OPTIONS = ['居中', '左对齐', '右对齐'];
const LINE_SPACING_MODE_OPTIONS = ['固定值(磅)', '最小值', '多倍行距'];
const HEADING_NUMBER_FORMAT_OPTIONS = [
  'decimal',
  'decimal_paren',
  'chinese',
  'chinese_paren',
  'mixed',
  'letter',
  'none',
];

const HEADING_NUMBER_FORMAT_LABELS: Record<string, string> = {
  decimal: '数字编号 (1. / 1.1 / 1.1.1)',
  decimal_paren: '数字括号 (1) / 1.1) / 1.1.1)',
  chinese: '中文编号 (一、/（一）/ 1.)',
  chinese_paren: '中文括号 （一）/ （二）',
  mixed: '混合编号 (一、/ 1.1 / 1.1.1)',
  letter: '字母编号 (A. / B. / a. / b.)',
  none: '无编号（仅按样式识别）',
};

const CONFIG_GROUPS: ConfigGroup[] = [
  {
    key: 'page',
    label: '页面设置',
    fields: [
      { key: 'margin_top', label: '上边距(cm)', type: 'number', step: 0.1, min: 0, max: 10 },
      { key: 'margin_bottom', label: '下边距(cm)', type: 'number', step: 0.1, min: 0, max: 10 },
      { key: 'margin_left', label: '左边距(cm)', type: 'number', step: 0.1, min: 0, max: 10 },
      { key: 'margin_right', label: '右边距(cm)', type: 'number', step: 0.1, min: 0, max: 10 },
      { key: 'force_a4', label: '强制A4纸张', type: 'checkbox' },
      { key: 'page_number_align', label: '页码对齐', type: 'select', options: ALIGN_OPTIONS },
      { key: 'page_number_font', label: '页码字体', type: 'select', options: FONT_OPTIONS },
      { key: 'page_number_size', label: '页码字号(磅)', type: 'number', step: 0.5, min: 5, max: 36 },
      { key: 'footer_distance', label: '页脚距离(cm)', type: 'number', step: 0.1, min: 0, max: 5 },
    ],
  },
  {
    key: 'heading_font',
    label: '标题字体',
    fields: [
      { key: 'title_font', label: '文件标题', type: 'select', options: FONT_OPTIONS },
      { key: 'h1_font', label: '一级标题', type: 'select', options: FONT_OPTIONS },
      { key: 'h2_font', label: '二级标题', type: 'select', options: FONT_OPTIONS },
      { key: 'h3_font', label: '三级标题', type: 'select', options: FONT_OPTIONS },
      { key: 'h4_font', label: '四级标题', type: 'select', options: FONT_OPTIONS },
      { key: 'h5_font', label: '五级标题', type: 'select', options: FONT_OPTIONS },
      { key: 'h6_font', label: '六级标题', type: 'select', options: FONT_OPTIONS },
      { key: 'h7_font', label: '七级标题', type: 'select', options: FONT_OPTIONS },
      { key: 'h8_font', label: '八级标题', type: 'select', options: FONT_OPTIONS },
    ],
  },
  {
    key: 'heading_size',
    label: '标题字号',
    fields: [
      { key: 'title_size', label: '文件标题(磅)', type: 'number', step: 0.5, min: 5, max: 72 },
      { key: 'h1_size', label: '一级标题(磅)', type: 'number', step: 0.5, min: 5, max: 72 },
      { key: 'h2_size', label: '二级标题(磅)', type: 'number', step: 0.5, min: 5, max: 72 },
      { key: 'h3_size', label: '三级标题(磅)', type: 'number', step: 0.5, min: 5, max: 72 },
      { key: 'h4_size', label: '四级标题(磅)', type: 'number', step: 0.5, min: 5, max: 72 },
      { key: 'h5_size', label: '五级标题(磅)', type: 'number', step: 0.5, min: 5, max: 72 },
      { key: 'h6_size', label: '六级标题(磅)', type: 'number', step: 0.5, min: 5, max: 72 },
      { key: 'h7_size', label: '七级标题(磅)', type: 'number', step: 0.5, min: 5, max: 72 },
      { key: 'h8_size', label: '八级标题(磅)', type: 'number', step: 0.5, min: 5, max: 72 },
    ],
  },
  {
    key: 'heading_style',
    label: '标题样式',
    fields: [
      { key: 'h1_bold', label: '一级标题加粗', type: 'checkbox' },
      { key: 'h2_bold', label: '二级标题加粗', type: 'checkbox' },
      { key: 'h3_bold', label: '三级标题加粗', type: 'checkbox' },
      { key: 'h4_bold', label: '四级标题加粗', type: 'checkbox' },
      { key: 'h5_bold', label: '五级标题加粗', type: 'checkbox' },
      { key: 'h6_bold', label: '六级标题加粗', type: 'checkbox' },
      { key: 'h7_bold', label: '七级标题加粗', type: 'checkbox' },
      { key: 'h8_bold', label: '八级标题加粗', type: 'checkbox' },
      { key: 'h1_space_before', label: '一级标题段前(磅)', type: 'number', step: 0.5, min: 0, max: 72 },
      { key: 'h1_space_after', label: '一级标题段后(磅)', type: 'number', step: 0.5, min: 0, max: 72 },
      { key: 'h2_space_before', label: '二级标题段前(磅)', type: 'number', step: 0.5, min: 0, max: 72 },
      { key: 'h2_space_after', label: '二级标题段后(磅)', type: 'number', step: 0.5, min: 0, max: 72 },
      { key: 'h3_space_before', label: '三级标题段前(磅)', type: 'number', step: 0.5, min: 0, max: 72 },
      { key: 'h3_space_after', label: '三级标题段后(磅)', type: 'number', step: 0.5, min: 0, max: 72 },
      { key: 'h4_space_before', label: '四级标题段前(磅)', type: 'number', step: 0.5, min: 0, max: 72 },
      { key: 'h4_space_after', label: '四级标题段后(磅)', type: 'number', step: 0.5, min: 0, max: 72 },
      { key: 'h5_space_before', label: '五级标题段前(磅)', type: 'number', step: 0.5, min: 0, max: 72 },
      { key: 'h5_space_after', label: '五级标题段后(磅)', type: 'number', step: 0.5, min: 0, max: 72 },
      { key: 'title_line_spacing', label: '标题行距(磅)', type: 'number', step: 1, min: 10, max: 72 },
    ],
  },
  {
    key: 'body',
    label: '正文设置',
    fields: [
      { key: 'body_font', label: '正文字体', type: 'select', options: FONT_OPTIONS },
      { key: 'body_size', label: '正文字号(磅)', type: 'number', step: 0.5, min: 5, max: 36 },
      { key: 'line_spacing', label: '行距(磅)', type: 'number', step: 1, min: 10, max: 72 },
      { key: 'line_spacing_mode', label: '行距模式', type: 'select', options: LINE_SPACING_MODE_OPTIONS },
      { key: 'left_indent_cm', label: '左缩进(cm)', type: 'number', step: 0.1, min: 0, max: 10 },
      { key: 'right_indent_cm', label: '右缩进(cm)', type: 'number', step: 0.1, min: 0, max: 10 },
      { key: 'english_font', label: '英文字体', type: 'select', options: FONT_OPTIONS },
      { key: 'use_custom_english_font', label: '启用自定义英文字体', type: 'checkbox' },
      { key: 'indent_h4', label: 'H4缩进(twips)', type: 'number', step: 10, min: 0, max: 2000 },
      { key: 'indent_h5', label: 'H5缩进(twips)', type: 'number', step: 10, min: 0, max: 2000 },
    ],
  },
  {
    key: 'other_font',
    label: '其他字体/字号',
    fields: [
      { key: 'subtitle_font', label: '副题字体', type: 'select', options: FONT_OPTIONS },
      { key: 'subtitle_size', label: '副题字号(磅)', type: 'number', step: 0.5, min: 5, max: 72 },
      { key: 'subtitle_line_spacing', label: '副题行距(磅)', type: 'number', step: 1, min: 10, max: 72 },
      { key: 'attachment_font', label: '附件标题字体', type: 'select', options: FONT_OPTIONS },
      { key: 'attachment_size', label: '附件标题字号(磅)', type: 'number', step: 0.5, min: 5, max: 72 },
      { key: 'table_caption_font', label: '表标题字体', type: 'select', options: FONT_OPTIONS },
      { key: 'table_caption_size', label: '表标题字号(磅)', type: 'number', step: 0.5, min: 5, max: 36 },
      { key: 'figure_caption_font', label: '图标题字体', type: 'select', options: FONT_OPTIONS },
      { key: 'figure_caption_size', label: '图标题字号(磅)', type: 'number', step: 0.5, min: 5, max: 36 },
    ],
  },
  {
    key: 'table',
    label: '表格设置',
    fields: [
      { key: 'enable_table_formatting', label: '启用表格格式化', type: 'checkbox' },
      { key: 'table_font', label: '表格字体', type: 'select', options: FONT_OPTIONS },
      { key: 'table_header_font', label: '表头字体', type: 'select', options: FONT_OPTIONS },
      { key: 'table_size', label: '表格字号(磅)', type: 'number', step: 0.5, min: 5, max: 36 },
      { key: 'table_header_bold', label: '表头加粗', type: 'checkbox' },
      { key: 'table_smart_align', label: '智能对齐', type: 'checkbox' },
      { key: 'table_auto_col_width', label: '自动列宽', type: 'checkbox' },
      { key: 'table_width_percent', label: '表格宽度(%)', type: 'number', step: 5, min: 50, max: 100 },
      { key: 'table_unified_borders', label: '统一边框', type: 'checkbox' },
      { key: 'table_border_size_pt', label: '边框粗细(磅)', type: 'number', step: 0.25, min: 0, max: 3 },
      { key: 'table_row_height_cm', label: '行高(cm)', type: 'number', step: 0.1, min: 0, max: 5 },
      { key: 'table_line_spacing', label: '表格行距(磅)', type: 'number', step: 1, min: 10, max: 72 },
    ],
  },
  {
    key: 'advanced',
    label: '高级选项',
    fields: [
      { key: 'set_outline', label: '设置文档大纲', type: 'checkbox' },
      { key: 'heading_number_format', label: '标题编号格式', type: 'select', options: HEADING_NUMBER_FORMAT_OPTIONS, optionLabels: HEADING_NUMBER_FORMAT_LABELS },
      { key: 'enable_attachment_formatting', label: '附件格式化', type: 'checkbox' },
      { key: 'normalize_punctuation', label: '标点符号规范化', type: 'checkbox' },
      { key: 'bold_before_colon', label: '冒号前加粗', type: 'checkbox' },
    ],
  },
];

export default function FormatPage() {
  const [pageTab, setPageTab] = useState<PageTab>('format');
  const [file, setFile] = useState<File | null>(null);
  const [template, setTemplate] = useState<string>('default');
  const [mode, setMode] = useState<FormatMode>('format');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string>('');
  const [checkResult, setCheckResult] = useState<Record<string, unknown> | null>(null);
  const [diffResult, setDiffResult] = useState<Record<string, unknown> | null>(null);
  const [formatResult, setFormatResult] = useState<Record<string, unknown> | null>(null);
  const [beautifyResult, setBeautifyResult] = useState<Record<string, unknown> | null>(null);
  const [templates, setTemplates] = useState<Array<{ name: string; description: string }>>([]);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [configTemplate, setConfigTemplate] = useState<string>('default');
  const [configData, setConfigData] = useState<Record<string, unknown>>({});
  const [configOriginal, setConfigOriginal] = useState<Record<string, unknown>>({});
  const [configSaving, setConfigSaving] = useState(false);
  const [configMessage, setConfigMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
  const [newTemplateName, setNewTemplateName] = useState('');
  const [showNewTemplate, setShowNewTemplate] = useState(false);
  const [expandedGroups, setExpandedGroups] = useState<Record<string, boolean>>({
    page: true, heading_font: true, heading_size: true, heading_style: false,
    body: true, other_font: false, table: true, advanced: false,
  });

  const loadTemplates = useCallback(async () => {
    try {
      const res = await formatApi.listTemplates();
      setTemplates(res.data.templates || []);
    } catch (e) {
      console.error('加载模板列表失败', e);
    }
  }, []);

  const loadTemplateConfig = useCallback(async (name: string) => {
    try {
      const res = await formatApi.getTemplate(name);
      const cfg = res.data.config || {};
      setConfigData({ ...cfg });
      setConfigOriginal({ ...cfg });
    } catch (e) {
      console.error('加载模板配置失败', e);
    }
  }, []);

  useEffect(() => {
    loadTemplates();
  }, [loadTemplates]);

  useEffect(() => {
    if (pageTab === 'config') {
      loadTemplateConfig(configTemplate);
    }
  }, [configTemplate, pageTab, loadTemplateConfig]);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      const selected = e.target.files[0];
      if (!selected.name.endsWith('.docx')) {
        setError('请上传.docx格式的Word文件');
        return;
      }
      setFile(selected);
      setError('');
      setCheckResult(null);
      setDiffResult(null);
      setFormatResult(null);
      setBeautifyResult(null);
    }
  };

  const handleExecute = async () => {
    if (!file) {
      setError('请先上传文件');
      return;
    }
    setLoading(true);
    setError('');

    try {
      if (mode === 'check') {
        const res = await formatApi.checkFormat(file, template);
        setCheckResult(res.data);
      } else if (mode === 'diff') {
        const res = await formatApi.diffFormat(file, template);
        setDiffResult(res.data);
      } else if (mode === 'beautify') {
        const res = await formatApi.beautify(file);
        setBeautifyResult(res.data);
      } else {
        const res = await formatApi.format(file, template, 'format');
        setFormatResult(res.data);
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : '操作失败');
    } finally {
      setLoading(false);
    }
  };

  const handleConfigChange = (key: string, value: unknown) => {
    setConfigData(prev => ({ ...prev, [key]: value }));
  };

  const handleSaveConfig = async () => {
    setConfigSaving(true);
    setConfigMessage(null);
    try {
      await formatApi.saveTemplate(configTemplate, configData);
      setConfigOriginal({ ...configData });
      setConfigMessage({ type: 'success', text: `模板 "${configTemplate}" 保存成功` });
      await loadTemplates();
    } catch (e: unknown) {
      setConfigMessage({ type: 'error', text: e instanceof Error ? e.message : '保存失败' });
    } finally {
      setConfigSaving(false);
    }
  };

  const handleResetConfig = () => {
    setConfigData({ ...configOriginal });
    setConfigMessage(null);
  };

  const handleCreateTemplate = async () => {
    if (!newTemplateName.trim()) return;
    setConfigSaving(true);
    setConfigMessage(null);
    try {
      await formatApi.saveTemplate(newTemplateName.trim(), configData);
      setConfigTemplate(newTemplateName.trim());
      setShowNewTemplate(false);
      setNewTemplateName('');
      setConfigMessage({ type: 'success', text: `模板 "${newTemplateName.trim()}" 创建成功` });
      await loadTemplates();
    } catch (e: unknown) {
      setConfigMessage({ type: 'error', text: e instanceof Error ? e.message : '创建失败' });
    } finally {
      setConfigSaving(false);
    }
  };

  const handleDuplicateTemplate = async () => {
    const newName = `${configTemplate}_copy`;
    setConfigSaving(true);
    setConfigMessage(null);
    try {
      await formatApi.saveTemplate(newName, configData);
      setConfigTemplate(newName);
      setConfigMessage({ type: 'success', text: `已复制为模板 "${newName}"` });
      await loadTemplates();
    } catch (e: unknown) {
      setConfigMessage({ type: 'error', text: e instanceof Error ? e.message : '复制失败' });
    } finally {
      setConfigSaving(false);
    }
  };

  const handleDeleteTemplate = async () => {
    if (configTemplate === 'default') {
      setConfigMessage({ type: 'error', text: '内置模板不可删除' });
      return;
    }
    setConfigSaving(true);
    setConfigMessage(null);
    try {
      const res = await formatApi.deleteTemplate(configTemplate);
      if (res.data.success === false) {
        setConfigMessage({ type: 'error', text: res.data.error || '删除失败' });
      } else {
        setConfigTemplate('default');
        setConfigMessage({ type: 'success', text: '模板已删除' });
        await loadTemplates();
      }
    } catch (e: unknown) {
      setConfigMessage({ type: 'error', text: e instanceof Error ? e.message : '删除失败' });
    } finally {
      setConfigSaving(false);
    }
  };

  const toggleGroup = (key: string) => {
    setExpandedGroups(prev => ({ ...prev, [key]: !prev[key] }));
  };

  const isConfigModified = Object.keys(configData).some(
    k => JSON.stringify(configData[k]) !== JSON.stringify(configOriginal[k])
  );

  const modeOptions: Array<{ key: FormatMode; label: string; icon: React.ReactNode; desc: string }> = [
    { key: 'format', label: '一键排版', icon: <Wand2 size={16} />, desc: '自动应用模板格式' },
    { key: 'check', label: '格式检查', icon: <CheckCircle size={16} />, desc: '检查格式合规性' },
    { key: 'diff', label: '差异对比', icon: <Eye size={16} />, desc: '对比期望与实际格式' },
    { key: 'beautify', label: 'XML美化', icon: <Palette size={16} />, desc: '深度XML级别美化' },
  ];

  const renderConfigField = (field: ConfigField) => {
    const value = configData[field.key];

    if (field.type === 'checkbox') {
      return (
        <label key={field.key} style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer', padding: '4px 0' }}>
          <input
            type="checkbox"
            checked={!!value}
            onChange={(e) => handleConfigChange(field.key, e.target.checked)}
            style={{ width: '16px', height: '16px', cursor: 'pointer' }}
          />
          <span style={{ fontSize: '13px' }}>{field.label}</span>
        </label>
      );
    }

    if (field.type === 'select') {
      return (
        <div key={field.key} style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '4px 0' }}>
          <span style={{ fontSize: '13px', color: 'var(--color-text-secondary)', minWidth: '120px' }}>{field.label}</span>
          <select
            value={String(value || '')}
            onChange={(e) => handleConfigChange(field.key, e.target.value)}
            style={{ flex: 1, padding: '6px 10px', border: '1px solid var(--color-border)', borderRadius: '6px', fontSize: '13px', background: 'var(--color-surface)' }}
          >
            {field.options?.map(opt => (
              <option key={opt} value={opt}>{field.optionLabels?.[opt] || opt}</option>
            ))}
          </select>
        </div>
      );
    }

    if (field.type === 'number') {
      return (
        <div key={field.key} style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '4px 0' }}>
          <span style={{ fontSize: '13px', color: 'var(--color-text-secondary)', minWidth: '120px' }}>{field.label}</span>
          <input
            type="number"
            value={value != null ? String(value) : ''}
            step={field.step || 1}
            min={field.min}
            max={field.max}
            onChange={(e) => handleConfigChange(field.key, parseFloat(e.target.value) || 0)}
            style={{ flex: 1, padding: '6px 10px', border: '1px solid var(--color-border)', borderRadius: '6px', fontSize: '13px', background: 'var(--color-surface)' }}
          />
        </div>
      );
    }

    return (
      <div key={field.key} style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '4px 0' }}>
        <span style={{ fontSize: '13px', color: 'var(--color-text-secondary)', minWidth: '120px' }}>{field.label}</span>
        <input
          type="text"
          value={String(value || '')}
          onChange={(e) => handleConfigChange(field.key, e.target.value)}
          style={{ flex: 1, padding: '6px 10px', border: '1px solid var(--color-border)', borderRadius: '6px', fontSize: '13px', background: 'var(--color-surface)' }}
        />
      </div>
    );
  };

  const renderCheckResult = () => {
    if (!checkResult) return null;
    const data = checkResult as Record<string, unknown>;
    const issues = (data.issues || []) as FormatIssue[];
    const complianceRate = data.compliance_rate as number || 0;

    return (
      <div style={{ marginTop: '20px' }}>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr', gap: '12px', marginBottom: '16px' }}>
          <div style={{ padding: '16px', background: complianceRate >= 90 ? '#ecfdf5' : complianceRate >= 60 ? '#fffbeb' : '#fef2f2', borderRadius: '8px', textAlign: 'center' }}>
            <div style={{ fontSize: '28px', fontWeight: 700, color: complianceRate >= 90 ? '#059669' : complianceRate >= 60 ? '#d97706' : '#dc2626' }}>
              {complianceRate}%
            </div>
            <div style={{ fontSize: '12px', color: 'var(--color-text-secondary)', marginTop: '4px' }}>合规率</div>
          </div>
          <div style={{ padding: '16px', background: '#fef2f2', borderRadius: '8px', textAlign: 'center' }}>
            <div style={{ fontSize: '28px', fontWeight: 700, color: '#dc2626' }}>{data.font_issues as number || 0}</div>
            <div style={{ fontSize: '12px', color: 'var(--color-text-secondary)', marginTop: '4px' }}>字体问题</div>
          </div>
          <div style={{ padding: '16px', background: '#fffbeb', borderRadius: '8px', textAlign: 'center' }}>
            <div style={{ fontSize: '28px', fontWeight: 700, color: '#d97706' }}>{data.size_issues as number || 0}</div>
            <div style={{ fontSize: '12px', color: 'var(--color-text-secondary)', marginTop: '4px' }}>字号问题</div>
          </div>
          <div style={{ padding: '16px', background: '#eff6ff', borderRadius: '8px', textAlign: 'center' }}>
            <div style={{ fontSize: '28px', fontWeight: 700, color: '#2563eb' }}>{data.margin_issues as number || 0}</div>
            <div style={{ fontSize: '12px', color: 'var(--color-text-secondary)', marginTop: '4px' }}>边距问题</div>
          </div>
        </div>

        {issues.length > 0 && (
          <div>
            <h4 style={{ fontSize: '14px', fontWeight: 600, marginBottom: '8px' }}>问题详情</h4>
            <div style={{ maxHeight: '300px', overflow: 'auto', border: '1px solid var(--color-border)', borderRadius: '8px' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '12px' }}>
                <thead>
                  <tr style={{ background: '#f8fafc' }}>
                    <th style={{ padding: '8px', textAlign: 'left', borderBottom: '1px solid var(--color-border)' }}>类型</th>
                    <th style={{ padding: '8px', textAlign: 'left', borderBottom: '1px solid var(--color-border)' }}>期望</th>
                    <th style={{ padding: '8px', textAlign: 'left', borderBottom: '1px solid var(--color-border)' }}>实际</th>
                    <th style={{ padding: '8px', textAlign: 'left', borderBottom: '1px solid var(--color-border)' }}>位置</th>
                  </tr>
                </thead>
                <tbody>
                  {issues.slice(0, 50).map((issue, idx) => (
                    <tr key={idx} style={{ borderBottom: '1px solid var(--color-border)' }}>
                      <td style={{ padding: '6px 8px' }}>
                        <span style={{
                          padding: '2px 6px',
                          borderRadius: '4px',
                          fontSize: '11px',
                          background: issue.type === 'font_mismatch' ? '#fef2f2' : issue.type === 'size_mismatch' ? '#fffbeb' : issue.type === 'indent_missing' ? '#eff6ff' : '#f8fafc',
                          color: issue.type === 'font_mismatch' ? '#dc2626' : issue.type === 'size_mismatch' ? '#d97706' : '#2563eb',
                        }}>
                          {issue.type === 'font_mismatch' ? '字体' : issue.type === 'size_mismatch' ? '字号' : issue.type === 'indent_missing' ? '缩进' : issue.type === 'bold_mismatch' ? '加粗' : '边距'}
                        </span>
                      </td>
                      <td style={{ padding: '6px 8px' }}>{issue.expected}</td>
                      <td style={{ padding: '6px 8px', color: '#dc2626' }}>{issue.actual}</td>
                      <td style={{ padding: '6px 8px', color: 'var(--color-text-secondary)', maxWidth: '200px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {issue.text_preview || issue.detail || ''}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    );
  };

  const renderDiffResult = () => {
    if (!diffResult) return null;
    const data = diffResult as Record<string, unknown>;
    const diffs = (data.diffs || []) as FormatDiff[];
    const autoFixable = data.auto_fixable as number || 0;

    return (
      <div style={{ marginTop: '20px' }}>
        <div style={{ display: 'flex', gap: '12px', marginBottom: '16px' }}>
          <div style={{ padding: '12px 16px', background: '#fef2f2', borderRadius: '8px', fontSize: '14px' }}>
            <span style={{ fontWeight: 600, color: '#dc2626' }}>{data.diff_count as number || 0}</span> 处差异
          </div>
          <div style={{ padding: '12px 16px', background: '#ecfdf5', borderRadius: '8px', fontSize: '14px' }}>
            <span style={{ fontWeight: 600, color: '#059669' }}>{autoFixable}</span> 处可自动修正
          </div>
        </div>

        {diffs.length > 0 && (
          <div style={{ border: '1px solid var(--color-border)', borderRadius: '8px', overflow: 'auto', maxHeight: '400px' }}>
            {diffs.slice(0, 100).map((diff, idx) => (
              <div key={idx} style={{ padding: '8px 12px', borderBottom: '1px solid var(--color-border)', display: 'flex', gap: '12px', fontSize: '12px' }}>
                <span style={{ color: 'var(--color-text-secondary)', minWidth: '150px', overflow: 'hidden', textOverflow: 'ellipsis' }}>{diff.location}</span>
                <span style={{ color: '#475569', minWidth: '80px' }}>{diff.property}</span>
                <span style={{ color: '#059669', minWidth: '100px' }}>期望: {diff.expected}</span>
                <span style={{ color: '#dc2626', minWidth: '100px' }}>实际: {diff.actual}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    );
  };

  const renderFormatResult = () => {
    if (!formatResult) return null;
    const data = formatResult as Record<string, unknown>;
    const stats = data.stats as Record<string, unknown> || {};

    return (
      <div style={{ marginTop: '20px', padding: '20px', background: '#ecfdf5', borderRadius: '12px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '12px' }}>
          <CheckCircle size={20} color="#059669" />
          <span style={{ fontSize: '16px', fontWeight: 600, color: '#059669' }}>排版完成</span>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr', gap: '12px' }}>
          <div style={{ fontSize: '13px' }}>处理段落: <strong>{stats.paragraphs as number || 0}</strong></div>
          <div style={{ fontSize: '13px' }}>标题格式化: <strong>{stats.headings as number || 0}</strong></div>
          <div style={{ fontSize: '13px' }}>正文格式化: <strong>{stats.body as number || 0}</strong></div>
          <div style={{ fontSize: '13px' }}>表格格式化: <strong>{stats.tables as number || 0}</strong></div>
        </div>
        {data.output_path ? (
          <div style={{ marginTop: '12px' }}>
            <button
              onClick={() => {
                const path = data.output_path as string;
                const link = document.createElement('a');
                link.href = `/api/format/download?path=${encodeURIComponent(path)}`;
                link.download = '';
                link.click();
              }}
              style={{
                padding: '8px 16px',
                background: '#059669',
                color: 'white',
                border: 'none',
                borderRadius: '6px',
                cursor: 'pointer',
                fontSize: '13px',
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
              }}
            >
              <Download size={14} /> 下载排版后文件
            </button>
          </div>
        ) : null}
      </div>
    );
  };

  const renderBeautifyResult = () => {
    if (!beautifyResult) return null;
    const data = beautifyResult as Record<string, unknown>;
    const report = data.report as Record<string, unknown> || {};

    return (
      <div style={{ marginTop: '20px', padding: '20px', background: '#eff6ff', borderRadius: '12px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '12px' }}>
          <Palette size={20} color="#2563eb" />
          <span style={{ fontSize: '16px', fontWeight: 600, color: '#2563eb' }}>XML美化完成</span>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '12px', fontSize: '13px' }}>
          <div>H4样式应用: <strong>{report.h4_applied as number || 0}</strong></div>
          <div>H5样式应用: <strong>{report.h5_applied as number || 0}</strong></div>
          <div>重复前缀清理: <strong>{report.dup_stripped as number || 0}</strong></div>
          <div>正文缩进应用: <strong>{report.body_indent as number || 0}</strong></div>
          <div>编号优化: <strong>{(report.num_optimizations as unknown[] || []).length}</strong></div>
          <div>样式优化: <strong>{(report.style_optimizations as unknown[] || []).length}</strong></div>
        </div>
        {data.output_path ? (
          <div style={{ marginTop: '12px' }}>
            <button
              onClick={() => {
                const path = data.output_path as string;
                const link = document.createElement('a');
                link.href = `/api/format/download?path=${encodeURIComponent(path)}`;
                link.download = '';
                link.click();
              }}
              style={{
                padding: '8px 16px',
                background: '#2563eb',
                color: 'white',
                border: 'none',
                borderRadius: '6px',
                cursor: 'pointer',
                fontSize: '13px',
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
              }}
            >
              <Download size={14} /> 下载美化后文件
            </button>
          </div>
        ) : null}
      </div>
    );
  };

  const renderFormatTab = () => (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '20px' }}>
      <div style={{ background: 'var(--color-surface)', borderRadius: '12px', padding: '24px', border: '1px solid var(--color-border)' }}>
        <h3 style={{ fontSize: '16px', fontWeight: 600, marginBottom: '16px' }}>上传文件</h3>

        <div
          onClick={() => fileInputRef.current?.click()}
          style={{
            border: '2px dashed var(--color-border)',
            borderRadius: '12px',
            padding: '40px',
            textAlign: 'center',
            cursor: 'pointer',
            transition: 'all 0.2s',
            background: file ? '#ecfdf5' : '#f8fafc',
            borderColor: file ? '#059669' : 'var(--color-border)',
          }}
        >
          <Upload size={32} color={file ? '#059669' : '#94a3b8'} style={{ margin: '0 auto 12px' }} />
          <div style={{ fontSize: '14px', fontWeight: 500 }}>
            {file ? file.name : '点击上传 .docx 文件'}
          </div>
          {file && <div style={{ fontSize: '12px', color: '#059669', marginTop: '4px' }}>文件大小: {(file.size / 1024).toFixed(1)} KB</div>}
        </div>
        <input ref={fileInputRef} type="file" accept=".docx" onChange={handleFileChange} style={{ display: 'none' }} />

        <div style={{ marginTop: '16px' }}>
          <label style={{ fontSize: '13px', color: 'var(--color-text-secondary)', display: 'block', marginBottom: '6px' }}>排版模板</label>
          <select
            value={template}
            onChange={(e) => setTemplate(e.target.value)}
            style={{ width: '100%', padding: '8px 12px', border: '1px solid var(--color-border)', borderRadius: '6px', fontSize: '14px' }}
          >
            {templates.map(t => (
              <option key={t.name} value={t.name}>{t.name} - {t.description}</option>
            ))}
          </select>
          <div style={{ marginTop: '4px' }}>
            <button
              onClick={() => { setConfigTemplate(template); setPageTab('config'); }}
              style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: '12px', color: 'var(--color-primary)', display: 'flex', alignItems: 'center', gap: '4px' }}
            >
              <Settings size={12} /> 编辑此模板配置
            </button>
          </div>
        </div>

        <div style={{ marginTop: '16px' }}>
          <label style={{ fontSize: '13px', color: 'var(--color-text-secondary)', display: 'block', marginBottom: '8px' }}>操作模式</label>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px' }}>
            {modeOptions.map(opt => (
              <div
                key={opt.key}
                onClick={() => setMode(opt.key)}
                style={{
                  padding: '10px',
                  border: `2px solid ${mode === opt.key ? 'var(--color-primary)' : 'var(--color-border)'}`,
                  borderRadius: '8px',
                  cursor: 'pointer',
                  background: mode === opt.key ? '#eff6ff' : 'transparent',
                  transition: 'all 0.2s',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '13px', fontWeight: 600 }}>
                  {opt.icon} {opt.label}
                </div>
                <div style={{ fontSize: '11px', color: 'var(--color-text-secondary)', marginTop: '2px' }}>{opt.desc}</div>
              </div>
            ))}
          </div>
        </div>

        <button
          onClick={handleExecute}
          disabled={loading || !file}
          style={{
            width: '100%',
            marginTop: '16px',
            padding: '10px',
            background: loading || !file ? '#94a3b8' : 'var(--color-primary)',
            color: 'white',
            border: 'none',
            borderRadius: '8px',
            cursor: loading || !file ? 'not-allowed' : 'pointer',
            fontSize: '14px',
            fontWeight: 600,
          }}
        >
          {loading ? '处理中...' : modeOptions.find(m => m.key === mode)?.label || '执行'}
        </button>
      </div>

      <div style={{ background: 'var(--color-surface)', borderRadius: '12px', padding: '24px', border: '1px solid var(--color-border)' }}>
        <h3 style={{ fontSize: '16px', fontWeight: 600, marginBottom: '16px' }}>处理结果</h3>

        {error && (
          <div style={{ padding: '12px', background: '#fef2f2', borderRadius: '8px', color: '#dc2626', fontSize: '13px', marginBottom: '16px', display: 'flex', alignItems: 'center', gap: '8px' }}>
            <AlertTriangle size={16} /> {error}
          </div>
        )}

        {!checkResult && !diffResult && !formatResult && !beautifyResult && !error && (
          <div style={{ textAlign: 'center', padding: '60px', color: 'var(--color-text-secondary)', fontSize: '14px' }}>
            <FileText size={48} color="#cbd5e1" style={{ margin: '0 auto 12px' }} />
            上传文件并选择操作模式后查看结果
          </div>
        )}

        {renderCheckResult()}
        {renderDiffResult()}
        {renderFormatResult()}
        {renderBeautifyResult()}
      </div>
    </div>
  );

  const renderConfigTab = () => (
    <div style={{ display: 'grid', gridTemplateColumns: '320px 1fr', gap: '20px' }}>
      <div style={{ background: 'var(--color-surface)', borderRadius: '12px', padding: '20px', border: '1px solid var(--color-border)' }}>
        <h3 style={{ fontSize: '16px', fontWeight: 600, marginBottom: '16px' }}>模板管理</h3>

        <div style={{ marginBottom: '16px' }}>
          <label style={{ fontSize: '13px', color: 'var(--color-text-secondary)', display: 'block', marginBottom: '6px' }}>当前模板</label>
          <select
            value={configTemplate}
            onChange={(e) => setConfigTemplate(e.target.value)}
            style={{ width: '100%', padding: '8px 12px', border: '1px solid var(--color-border)', borderRadius: '6px', fontSize: '14px' }}
          >
            {templates.map(t => (
              <option key={t.name} value={t.name}>{t.name}</option>
            ))}
          </select>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', marginBottom: '16px' }}>
          <button
            onClick={() => setShowNewTemplate(true)}
            style={{ padding: '8px 12px', background: 'var(--color-primary)', color: 'white', border: 'none', borderRadius: '6px', cursor: 'pointer', fontSize: '13px', display: 'flex', alignItems: 'center', gap: '6px', justifyContent: 'center' }}
          >
            <Plus size={14} /> 新建模板
          </button>
          <button
            onClick={handleDuplicateTemplate}
            style={{ padding: '8px 12px', background: '#0f766e', color: 'white', border: 'none', borderRadius: '6px', cursor: 'pointer', fontSize: '13px', display: 'flex', alignItems: 'center', gap: '6px', justifyContent: 'center' }}
          >
            <Copy size={14} /> 复制为自定义
          </button>
          <button
            onClick={handleDeleteTemplate}
            disabled={configTemplate === 'default' || configTemplate === 'government' || configTemplate === 'engineering'}
            style={{
              padding: '8px 12px',
              background: configTemplate === 'default' || configTemplate === 'government' || configTemplate === 'engineering' ? '#e5e7eb' : '#fef2f2',
              color: configTemplate === 'default' || configTemplate === 'government' || configTemplate === 'engineering' ? '#9ca3af' : '#dc2626',
              border: '1px solid var(--color-border)',
              borderRadius: '6px',
              cursor: configTemplate === 'default' || configTemplate === 'government' || configTemplate === 'engineering' ? 'not-allowed' : 'pointer',
              fontSize: '13px',
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              justifyContent: 'center',
            }}
          >
            <Trash2 size={14} /> 删除模板
          </button>
        </div>

        {showNewTemplate && (
          <div style={{ padding: '12px', border: '1px solid var(--color-border)', borderRadius: '8px', marginBottom: '12px' }}>
            <label style={{ fontSize: '13px', color: 'var(--color-text-secondary)', display: 'block', marginBottom: '4px' }}>模板名称</label>
            <input
              type="text"
              value={newTemplateName}
              onChange={(e) => setNewTemplateName(e.target.value)}
              placeholder="如: my_template"
              style={{ width: '100%', padding: '6px 10px', border: '1px solid var(--color-border)', borderRadius: '6px', fontSize: '13px', boxSizing: 'border-box', marginBottom: '8px' }}
            />
            <div style={{ display: 'flex', gap: '6px' }}>
              <button onClick={handleCreateTemplate} style={{ padding: '4px 12px', background: '#059669', color: 'white', border: 'none', borderRadius: '4px', cursor: 'pointer', fontSize: '12px' }}>创建</button>
              <button onClick={() => { setShowNewTemplate(false); setNewTemplateName(''); }} style={{ padding: '4px 12px', background: 'var(--color-surface)', border: '1px solid var(--color-border)', borderRadius: '4px', cursor: 'pointer', fontSize: '12px' }}>取消</button>
            </div>
          </div>
        )}

        <div style={{ borderTop: '1px solid var(--color-border)', paddingTop: '12px' }}>
          <h4 style={{ fontSize: '13px', fontWeight: 600, marginBottom: '8px' }}>配置分组</h4>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
            {CONFIG_GROUPS.map(g => (
              <div
                key={g.key}
                onClick={() => toggleGroup(g.key)}
                style={{
                  padding: '6px 8px',
                  borderRadius: '4px',
                  cursor: 'pointer',
                  fontSize: '12px',
                  background: expandedGroups[g.key] ? '#eff6ff' : 'transparent',
                  color: expandedGroups[g.key] ? 'var(--color-primary)' : 'var(--color-text)',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '4px',
                }}
              >
                {expandedGroups[g.key] ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                {g.label}
                <span style={{ marginLeft: 'auto', color: 'var(--color-text-secondary)', fontSize: '11px' }}>{g.fields.length}项</span>
              </div>
            ))}
          </div>
        </div>

        {isConfigModified && (
          <div style={{ marginTop: '12px', padding: '8px', background: '#fffbeb', borderRadius: '6px', fontSize: '12px', color: '#d97706', textAlign: 'center' }}>
            配置已修改，请保存
          </div>
        )}
      </div>

      <div style={{ background: 'var(--color-surface)', borderRadius: '12px', padding: '24px', border: '1px solid var(--color-border)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
          <h3 style={{ fontSize: '16px', fontWeight: 600 }}>
            模板配置 - {configTemplate}
          </h3>
          <div style={{ display: 'flex', gap: '8px' }}>
            <button
              onClick={handleResetConfig}
              disabled={!isConfigModified}
              style={{
                padding: '6px 14px',
                background: isConfigModified ? 'var(--color-surface)' : '#e5e7eb',
                color: isConfigModified ? 'var(--color-text)' : '#9ca3af',
                border: '1px solid var(--color-border)',
                borderRadius: '6px',
                cursor: isConfigModified ? 'pointer' : 'not-allowed',
                fontSize: '13px',
                display: 'flex',
                alignItems: 'center',
                gap: '4px',
              }}
            >
              <RotateCcw size={14} /> 重置
            </button>
            <button
              onClick={handleSaveConfig}
              disabled={configSaving || !isConfigModified}
              style={{
                padding: '6px 14px',
                background: configSaving || !isConfigModified ? '#94a3b8' : '#059669',
                color: 'white',
                border: 'none',
                borderRadius: '6px',
                cursor: configSaving || !isConfigModified ? 'not-allowed' : 'pointer',
                fontSize: '13px',
                display: 'flex',
                alignItems: 'center',
                gap: '4px',
              }}
            >
              <Save size={14} /> {configSaving ? '保存中...' : '保存配置'}
            </button>
          </div>
        </div>

        {configMessage && (
          <div style={{
            marginBottom: '12px',
            padding: '8px 12px',
            borderRadius: '6px',
            fontSize: '13px',
            background: configMessage.type === 'success' ? '#ecfdf5' : '#fef2f2',
            color: configMessage.type === 'success' ? '#059669' : '#dc2626',
          }}>
            {configMessage.text}
          </div>
        )}

        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          {CONFIG_GROUPS.map(group => (
            <div key={group.key} style={{ border: '1px solid var(--color-border)', borderRadius: '8px', overflow: 'hidden' }}>
              <div
                onClick={() => toggleGroup(group.key)}
                style={{
                  padding: '10px 16px',
                  background: '#f8fafc',
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  borderBottom: expandedGroups[group.key] ? '1px solid var(--color-border)' : 'none',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  {expandedGroups[group.key] ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                  <span style={{ fontSize: '14px', fontWeight: 600 }}>{group.label}</span>
                </div>
                <span style={{ fontSize: '12px', color: 'var(--color-text-secondary)' }}>{group.fields.length} 项配置</span>
              </div>
              {expandedGroups[group.key] && (
                <div style={{ padding: '12px 16px', display: 'grid', gridTemplateColumns: group.fields.some(f => f.type === 'checkbox') ? '1fr 1fr' : '1fr', gap: group.fields.some(f => f.type === 'checkbox') ? '4px 16px' : '6px' }}>
                  {group.fields.map(field => renderConfigField(field))}
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );

  return (
    <div className="page-fade-in">
      <StepHeader
        step={4}
        title="文档输出"
        subtitle="一键排版→格式检查→差异对比→PDF导出，模板灵活配置"
        color="#475569"
      />

      <div style={{ display: 'flex', gap: '8px', marginBottom: '20px' }}>
        {([
          { key: 'format' as PageTab, label: '排版操作', icon: <Wand2 size={14} /> },
          { key: 'config' as PageTab, label: '模板配置', icon: <Settings size={14} /> },
        ]).map(tab => (
          <button
            key={tab.key}
            onClick={() => setPageTab(tab.key)}
            style={{
              padding: '8px 16px',
              background: pageTab === tab.key ? 'var(--color-primary)' : 'var(--color-surface)',
              color: pageTab === tab.key ? 'white' : 'var(--color-text)',
              border: `1px solid ${pageTab === tab.key ? 'var(--color-primary)' : 'var(--color-border)'}`,
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

      {pageTab === 'format' && renderFormatTab()}
      {pageTab === 'config' && renderConfigTab()}
    </div>
  );
}
