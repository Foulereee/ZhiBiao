import { useNavigate } from 'react-router-dom';
import { ArrowRight, CheckCircle2 } from 'lucide-react';

interface StepHeaderProps {
  step: number;
  title: string;
  subtitle: string;
  color: string;
  nextPath?: string;
  nextLabel?: string;
}

const pipelineSteps = [
  { path: '/interpret', label: '招标解读', color: '#3b82f6' },
  { path: '/generate', label: '投标生成', color: '#059669' },
  { path: '/check', label: '投标检查', color: '#d97706' },
  { path: '/format', label: '文档输出', color: '#475569' },
];

export default function StepHeader({ step, title, subtitle, color, nextPath, nextLabel }: StepHeaderProps) {
  const navigate = useNavigate();

  return (
    <div className="step-slide-in" style={{
      background: 'var(--color-surface)',
      borderRadius: '14px',
      padding: '20px 24px',
      border: '1px solid var(--color-border)',
      marginBottom: '20px',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      gap: '20px',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '16px', flex: 1 }}>
        <div style={{
          width: '44px',
          height: '44px',
          borderRadius: '12px',
          background: `linear-gradient(135deg, ${color}, ${color}cc)`,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          flexShrink: 0,
          boxShadow: `0 4px 12px ${color}30`,
        }}>
          <span style={{ color: 'white', fontSize: '18px', fontWeight: 800 }}>{step}</span>
        </div>

        <div style={{ flex: 1 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '4px' }}>
            <h2 style={{ fontSize: '17px', fontWeight: 700, color: 'var(--color-text)', margin: 0 }}>{title}</h2>
            <span style={{
              fontSize: '11px',
              padding: '2px 8px',
              borderRadius: '6px',
              background: `${color}12`,
              color: color,
              fontWeight: 500,
            }}>
              Step {step}/4
            </span>
          </div>
          <p style={{ fontSize: '13px', color: 'var(--color-text-secondary)', margin: 0 }}>{subtitle}</p>
        </div>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: '6px', flexShrink: 0 }}>
        {pipelineSteps.map((s, idx) => {
          const isCurrent = idx + 1 === step;
          const isPast = idx + 1 < step;
          return (
            <div key={s.path} style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
              <div
                onClick={() => navigate(s.path)}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  width: isCurrent ? '28px' : '22px',
                  height: isCurrent ? '28px' : '22px',
                  borderRadius: '50%',
                  background: isCurrent
                    ? `linear-gradient(135deg, ${s.color}, ${s.color}cc)`
                    : isPast
                    ? s.color
                    : '#f1f5f9',
                  border: isCurrent
                    ? `2px solid ${s.color}`
                    : isPast
                    ? '2px solid transparent'
                    : '2px solid #e2e8f0',
                  cursor: 'pointer',
                  transition: 'all 0.2s ease',
                  boxShadow: isCurrent ? `0 0 0 3px ${s.color}25` : 'none',
                }}
                title={s.label}
              >
                {isPast ? (
                  <CheckCircle2 size={12} color="white" />
                ) : (
                  <span style={{
                    fontSize: isCurrent ? '11px' : '10px',
                    fontWeight: 600,
                    color: isCurrent ? 'white' : '#94a3b8',
                  }}>
                    {idx + 1}
                  </span>
                )}
              </div>
              {idx < pipelineSteps.length - 1 && (
                <div style={{
                  width: '16px',
                  height: '2px',
                  background: isPast
                    ? `linear-gradient(90deg, ${s.color}, ${pipelineSteps[idx + 1].color})`
                    : '#e2e8f0',
                  borderRadius: '1px',
                }} />
              )}
            </div>
          );
        })}
      </div>

      {nextPath && nextLabel && (
        <button
          onClick={() => navigate(nextPath)}
          style={{
            padding: '8px 16px',
            background: `linear-gradient(135deg, ${color}, ${color}cc)`,
            color: 'white',
            border: 'none',
            borderRadius: '8px',
            cursor: 'pointer',
            fontSize: '13px',
            fontWeight: 500,
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
            flexShrink: 0,
            boxShadow: `0 2px 8px ${color}30`,
            transition: 'all 0.15s ease',
          }}
          onMouseEnter={(e) => {
            (e.currentTarget as HTMLButtonElement).style.transform = 'translateY(-1px)';
            (e.currentTarget as HTMLButtonElement).style.boxShadow = `0 4px 12px ${color}40`;
          }}
          onMouseLeave={(e) => {
            (e.currentTarget as HTMLButtonElement).style.transform = 'translateY(0)';
            (e.currentTarget as HTMLButtonElement).style.boxShadow = `0 2px 8px ${color}30`;
          }}
        >
          {nextLabel} <ArrowRight size={14} />
        </button>
      )}
    </div>
  );
}
