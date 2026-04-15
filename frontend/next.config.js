/** @type {import('next').NextConfig} */
const isProd = process.env.NODE_ENV === 'production';
const apiProxyTarget = process.env.API_PROXY_TARGET || "http://127.0.0.1:8000";

const nextConfig = {
  output: isProd ? "export" : undefined,
};

if (!isProd) {
  nextConfig.rewrites = async () => [
    {
      source: "/api/:path*",
      destination: `${apiProxyTarget}/api/:path*`,
    },
  ];
}

module.exports = nextConfig;
