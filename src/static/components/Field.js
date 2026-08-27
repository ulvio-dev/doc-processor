function Label({ children }) {
  return (
    <label className="block text-xs font-medium text-gray-500 uppercase tracking-wider mb-1.5">
      {children}
    </label>
  );
}

const inputBase =
  'w-full border border-gray-300 rounded-lg px-3 py-2 text-sm bg-white ' +
  'focus:outline-none focus:ring-2 focus:ring-gray-900 focus:border-transparent';

function TextInput({ className = '', ...rest }) {
  return <input type="text" className={cx(inputBase, className)} {...rest} />;
}

function NumberInput({ className = '', ...rest }) {
  return <input type="number" className={cx(inputBase, className)} {...rest} />;
}

function Select({ className = '', children, ...rest }) {
  return (
    <select className={cx(inputBase, className)} {...rest}>
      {children}
    </select>
  );
}

function Checkbox({ label, checked, onChange, hint }) {
  return (
    <label className="flex items-start gap-2.5 cursor-pointer select-none">
      <input
        type="checkbox"
        checked={checked}
        onChange={e => onChange(e.target.checked)}
        className="mt-0.5 h-4 w-4 rounded border-gray-300 text-gray-900 focus:ring-gray-900"
      />
      <span>
        <span className="text-sm text-gray-800">{label}</span>
        {hint ? <span className="block text-xs text-gray-500">{hint}</span> : null}
      </span>
    </label>
  );
}

// Every parameter shows the service's real default, fetched from
// /api/contract, so the form documents docling's behaviour instead of
// restating a copy that can drift.
function Field({ label, help, defaultHint, children }) {
  return (
    <div>
      {label ? <Label>{label}</Label> : null}
      {children}
      {help ? <p className="text-xs text-gray-500 mt-1">{help}</p> : null}
      {defaultHint !== undefined && defaultHint !== null ? (
        <p className="text-xs text-gray-400 mt-1">
          default: <code className="font-mono">{String(defaultHint) || '(none)'}</code>
        </p>
      ) : null}
    </div>
  );
}

window.Label = Label;
window.TextInput = TextInput;
window.NumberInput = NumberInput;
window.Select = Select;
window.Checkbox = Checkbox;
window.Field = Field;
