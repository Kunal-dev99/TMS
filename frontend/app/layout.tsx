import type { Metadata } from 'next'
import { Inter, IBM_Plex_Mono } from 'next/font/google'
import './globals.css'
import { Toaster } from '@/components/ui/toaster'

const inter = Inter({
  subsets: ['latin'],
  display: 'swap',
  variable: '--font-sans',
})

const plexMono = IBM_Plex_Mono({
  subsets: ['latin'],
  weight: ['400', '500', '600'],
  display: 'swap',
  variable: '--font-mono',
})

export const metadata: Metadata = {
  title: 'Treasury Register | Fusion Practices',
  description: 'A control system for Treasury: Counterparty control, deal lifecycle, advisory layer, and policy checks.',
  icons: {
    icon: '/fusion-logo.png',
    shortcut: '/fusion-logo.png',
    apple: '/fusion-logo.png',
  },
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en" className={`${inter.variable} ${plexMono.variable}`}>
      <body className="font-sans antialiased min-h-screen bg-background text-foreground flex flex-col">
        <div className="flex-1">{children}</div>
        <footer className="border-t border-border py-3 text-center text-[11px] text-muted-foreground">
          Built by <span className="font-medium text-foreground">Fusion Practices</span>
        </footer>
        <Toaster />
      </body>
    </html>
  )
}
