/**
 * Next.js is the view layer and nothing else.
 *
 * It serves the page and rewrites /api to whichever API is running. Same
 * origin, so there is no cross origin configuration anywhere and there is
 * one URL to open on the day.
 *
 * TREASURY_API_ORIGIN points at the mock on 8001 until the real API on 8000
 * has the group in question. Nothing else in the frontend knows which is
 * answering, which is the whole point of the shapes being identical.
 */
const apiOrigin = process.env.TREASURY_API_ORIGIN ?? "http://127.0.0.1:8001";

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${apiOrigin}/api/:path*` }];
  },
};

export default nextConfig;
