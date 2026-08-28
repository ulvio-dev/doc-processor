// Neutral palette only: black, white, gray. Red is reserved for genuine
// failure states so it actually means something when it appears.
function Button({ variant = 'secondary', icon, iconSize = 15, children, className = '', ...rest }) {
  const base =
    'text-sm font-medium transition-colors flex items-center justify-center gap-1.5 ' +
    'disabled:opacity-40 disabled:cursor-not-allowed';
  const variants = {
    primary: 'bg-gray-900 text-white px-4 py-2 rounded-lg hover:bg-black',
    secondary: 'border border-gray-300 text-gray-700 px-4 py-2 rounded-lg hover:bg-gray-50',
    muted: 'text-gray-500 hover:text-gray-900',
  };
  return (
    <button className={cx(base, variants[variant], className)} {...rest}>
      {icon ? <Icon name={icon} size={iconSize} /> : null}
      {children}
    </button>
  );
}
window.Button = Button;
