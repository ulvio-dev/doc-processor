function Card({ children, className = '' }) {
  return (
    <div className={cx('bg-white rounded-xl border border-gray-200 overflow-hidden', className)}>
      {children}
    </div>
  );
}

function CardHeader({ title, subtitle, children }) {
  return (
    <div className="px-5 py-4 border-b border-gray-200 flex items-start justify-between gap-4">
      <div>
        <h2 className="text-sm font-semibold text-gray-900 uppercase tracking-wide">{title}</h2>
        {subtitle ? <p className="text-sm text-gray-500 mt-1">{subtitle}</p> : null}
      </div>
      {children ? <div className="flex items-center gap-2 shrink-0">{children}</div> : null}
    </div>
  );
}

function CardBody({ children, className = '' }) {
  return <div className={cx('px-5 py-4', className)}>{children}</div>;
}
window.Card = Card;
window.CardHeader = CardHeader;
window.CardBody = CardBody;
