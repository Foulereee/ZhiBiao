import { memo, useMemo, useState, useCallback, type ReactNode, isValidElement, Children } from 'react';
import ReactMarkdown from 'react-markdown';
import type { Components } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeRaw from 'rehype-raw';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism';
import { X } from 'lucide-react';

interface MarkdownRendererProps {
  children: string;
  components?: Components;
  className?: string;
}

function normalizeExternalUrl(value: string | undefined) {
  const raw = String(value || '').trim();
  if (!raw) return '';
  return /^www\./i.test(raw) ? `https://${raw}` : raw;
}

function isExternalHttpUrl(value: string) {
  return /^https?:\/\//i.test(value);
}

function ImagePreviewModal({ src, alt, onClose }: { src: string; alt: string; onClose: () => void }) {
  return (
    <div
      onClick={onClose}
      style={{
        position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
        background: 'rgba(0,0,0,0.75)', display: 'flex',
        alignItems: 'center', justifyContent: 'center', zIndex: 9999,
        cursor: 'pointer',
      }}
    >
      <div style={{ position: 'relative', maxWidth: '90vw', maxHeight: '90vh' }}>
        <img
          src={src} alt={alt}
          style={{ maxWidth: '90vw', maxHeight: '85vh', borderRadius: '8px', boxShadow: '0 8px 32px rgba(0,0,0,0.4)' }}
          onClick={(e) => e.stopPropagation()}
        />
        <button
          onClick={onClose}
          style={{
            position: 'absolute', top: '-12px', right: '-12px',
            width: '32px', height: '32px', borderRadius: '50%',
            background: 'white', border: 'none', cursor: 'pointer',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            boxShadow: '0 2px 8px rgba(0,0,0,0.2)',
          }}
        >
          <X size={16} />
        </button>
        <div style={{
          textAlign: 'center', marginTop: '8px', color: 'white',
          fontSize: '13px', opacity: 0.8,
        }}>
          {alt}
        </div>
      </div>
    </div>
  );
}

const MarkdownRenderer = memo(function MarkdownRenderer({ children, components, className }: MarkdownRendererProps) {
  const [previewImage, setPreviewImage] = useState<{ src: string; alt: string } | null>(null);

  const handlePreviewImage = useCallback((src: string, alt: string) => {
    setPreviewImage({ src, alt });
  }, []);

  const handleClosePreview = useCallback(() => {
    setPreviewImage(null);
  }, []);

  const mergedComponents = useMemo<Components>(() => {
    const base: Components = {
      a({ href, children, ...props }) {
        const externalUrl = normalizeExternalUrl(href);
        const isExternal = isExternalHttpUrl(externalUrl);
        return (
          <a
            {...props}
            href={isExternal ? externalUrl : href}
            rel={isExternal ? 'noreferrer' : props.rel}
            target={isExternal ? '_blank' : props.target}
          >
            {children as ReactNode}
          </a>
        );
      },
      pre({ children, ...props }) {
        const child = Children.count(children) === 1 ? Children.only(children) : null;
        if (isValidElement(child)) {
          const childProps = child.props as { className?: string; children?: ReactNode };
          const className = childProps.className || '';
          const langMatch = className.match(/language-(\w+)/);
          if (langMatch) {
            const language = langMatch[1];
            const code = String(childProps.children || '').replace(/\n$/, '');
            if (language === 'mermaid') {
              return (
                <div style={{ background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: '8px', padding: '16px', margin: '0.8em 0', overflow: 'auto' }}>
                  <div style={{ fontSize: '12px', color: '#64748b', marginBottom: '8px' }}>Mermaid 图表</div>
                  <pre style={{ margin: 0, fontSize: '13px', whiteSpace: 'pre-wrap' }}>{code}</pre>
                </div>
              );
            }
            try {
              return (
                <SyntaxHighlighter
                  style={oneDark}
                  language={language}
                  PreTag="div"
                  customStyle={{ borderRadius: '8px', margin: '0.8em 0', fontSize: '13px' }}
                >
                  {code}
                </SyntaxHighlighter>
              );
            } catch {
              return <pre {...props}>{children}</pre>;
            }
          }
        }
        return <pre {...props}>{children}</pre>;
      },
      img({ src, alt, ...props }) {
        const imageSrc = String(src || '');
        const imageAlt = String(alt || '');
        return (
          <img
            {...props}
            src={imageSrc}
            alt={imageAlt}
            style={{ cursor: imageSrc ? 'pointer' : 'default', maxWidth: '100%', borderRadius: '6px', margin: '0.5em 0' }}
            onClick={() => imageSrc && handlePreviewImage(imageSrc, imageAlt)}
          />
        );
      },
      table({ children, ...props }) {
        return (
          <div style={{ overflowX: 'auto', margin: '0.8em 0' }}>
            <table {...props}>{children as ReactNode}</table>
          </div>
        );
      },
    };

    if (components) {
      return { ...base, ...components };
    }
    return base;
  }, [components, handlePreviewImage]);

  return (
    <>
      <div className={className || 'markdown-content'}>
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          rehypePlugins={[rehypeRaw]}
          components={mergedComponents}
        >
          {children}
        </ReactMarkdown>
      </div>
      {previewImage && (
        <ImagePreviewModal
          src={previewImage.src}
          alt={previewImage.alt}
          onClose={handleClosePreview}
        />
      )}
    </>
  );
});

export default MarkdownRenderer;
