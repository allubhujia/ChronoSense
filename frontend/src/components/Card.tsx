import type { ReactNode } from "react";

interface CardProps {
  title?: string;
  icon?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}

/** White rounded panel matching the dashboard mockup. */
export default function Card({ title, icon, action, children, className = "" }: CardProps) {
  return (
    <section className={`rounded-2xl bg-white p-6 shadow-sm ring-1 ring-slate-200/70 ${className}`}>
      {(title || action) && (
        <header className="mb-5 flex items-center justify-between">
          <div className="flex items-center gap-2 text-slate-800">
            {icon && <span className="text-blue-600">{icon}</span>}
            {title && <h2 className="text-lg font-semibold">{title}</h2>}
          </div>
          {action}
        </header>
      )}
      {children}
    </section>
  );
}
