import React from 'react';

/**
 * Page wrapper: centers content and renders an optional title/subtitle.
 * @param {{title?: string, subtitle?: string, children: React.ReactNode}} props
 */
const Layout = ({ title, subtitle, children }) => {
  return (
    <div className="max-w-7xl mx-auto">
      {/* `cond && <jsx>` renders nothing when cond is falsy (a common JSX idiom). */}
      {title && (
        <div className="mb-6">
          <h1 className="text-2xl font-bold text-gray-900">{title}</h1>
          {subtitle && <p className="text-gray-500 text-sm mt-1">{subtitle}</p>}
        </div>
      )}
      {children}
    </div>
  );
};

export default Layout;
