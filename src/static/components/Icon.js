function Icon({ name, size = 16, className = '' }) {
  return (
    <span
      className={cx('iconify', className)}
      data-icon={name}
      data-width={size}
      data-height={size}
    />
  );
}
window.Icon = Icon;
