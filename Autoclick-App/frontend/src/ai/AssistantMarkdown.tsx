import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

export function AssistantMarkdown({ content }: { content: string }) {
  return (
    <div className="min-w-0 break-words whitespace-normal">
      <ReactMarkdown
        components={{
          a: ({ children, href }) => (
            <a
              className="font-semibold text-primary underline decoration-primary/40 underline-offset-2 hover:decoration-primary focus-visible:outline-none focus-visible:shadow-focus"
              href={href}
              rel="noopener noreferrer"
              target="_blank">
              {children}
            </a>
          ),
          blockquote: ({ children }) => (
            <blockquote className="my-2 border-l-3 border-primary/40 pl-3 text-text-muted">
              {children}
            </blockquote>
          ),
          code: ({ children, className }) => (
            <code className={`rounded bg-slate-200 px-1 py-0.5 font-mono text-[0.92em] ${className ?? ''}`}>
              {children}
            </code>
          ),
          em: ({ children }) => <em className="italic">{children}</em>,
          h1: ({ children }) => <h1 className="mt-3 mb-2 text-lg font-extrabold first:mt-0">{children}</h1>,
          h2: ({ children }) => <h2 className="mt-3 mb-2 text-base font-extrabold first:mt-0">{children}</h2>,
          h3: ({ children }) => <h3 className="mt-3 mb-1.5 text-sm font-extrabold first:mt-0">{children}</h3>,
          h4: ({ children }) => <h4 className="mt-3 mb-1 text-[13px] font-extrabold first:mt-0">{children}</h4>,
          hr: () => <hr className="my-3 border-0 border-t border-border" />,
          li: ({ children, className }) => <li className={`my-1 pl-0.5 ${className ?? ''}`}>{children}</li>,
          ol: ({ children }) => <ol className="my-2 list-decimal space-y-1 pl-5">{children}</ol>,
          p: ({ children }) => <p className="my-2 first:mt-0 last:mb-0">{children}</p>,
          pre: ({ children }) => (
            <pre className="my-3 max-w-full overflow-x-auto rounded-control bg-sidebar p-3 text-[12px] leading-5 text-slate-100 [&_code]:bg-transparent [&_code]:p-0 [&_code]:text-inherit">
              {children}
            </pre>
          ),
          strong: ({ children }) => <strong className="font-extrabold">{children}</strong>,
          table: ({ children }) => (
            <div className="my-3 max-w-full overflow-x-auto rounded-control border border-border">
              <table className="min-w-full border-collapse text-left text-[12px]">{children}</table>
            </div>
          ),
          td: ({ children }) => <td className="border-t border-border px-3 py-2 align-top">{children}</td>,
          th: ({ children }) => <th className="bg-slate-100 px-3 py-2 font-extrabold whitespace-nowrap">{children}</th>,
          ul: ({ children, className }) => (
            <ul className={`my-2 list-disc space-y-1 pl-5 [&.contains-task-list]:list-none [&.contains-task-list]:pl-0 [&_input]:mr-2 ${className ?? ''}`}>
              {children}
            </ul>
          ),
        }}
        remarkPlugins={[remarkGfm]}>
        {content}
      </ReactMarkdown>
    </div>
  );
}
