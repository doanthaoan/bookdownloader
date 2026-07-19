import React from 'react';

const Layout = ({ title, subtitle, children }) => {
  return (
    <div className="max-w-6xl mx-auto">
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
