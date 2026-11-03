/** @type {import('next').NextConfig} */
const backendUrl = process.env.BACKEND_URL || 'http://127.0.0.1:8000';

const nextConfig = {
  // Skip ESLint during production build (lint in CI separately)
  eslint: {
    ignoreDuringBuilds: true,
  },
  // Skip TS type-check during build for speed (tsc runs separately)
  typescript: {
    ignoreBuildErrors: false,
  },
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: `${backendUrl}/:path*`,
      },
    ];
  },
};

export default nextConfig;
