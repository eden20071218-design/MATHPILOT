import type { NextConfig } from "next";

// Linux Docker uses standalone; Windows local builds do not require symlink privileges.
const nextConfig: NextConfig = {
  output: process.platform === "win32" ? undefined : "standalone",
  async rewrites() {
    return [{ source: '/api/:path*', destination: (process.env.INTERNAL_API_URL || 'http://127.0.0.1:8000') + '/api/:path*' }];
  },
  async headers() {
    return [{ source: '/:path*', headers: [
      {key:'X-Content-Type-Options',value:'nosniff'},
      {key:'Referrer-Policy',value:'same-origin'},
      {key:'X-Frame-Options',value:'DENY'},
    ]}];
  },
};
export default nextConfig;

