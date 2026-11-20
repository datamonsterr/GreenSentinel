import { localTestAuthentication } from '@/lib/route-authorization';
import type { Metadata } from 'next'
import { ClerkProvider } from '@clerk/nextjs'
import { LocaleProvider } from '@/lib/locale'
import { Geist, Geist_Mono } from 'next/font/google'
import './globals.css'

const geistSans = Geist({
  variable: '--font-geist-sans',
  subsets: ['latin'],
})

const geistMono = Geist_Mono({
  variable: '--font-geist-mono',
  subsets: ['latin'],
})

export const metadata: Metadata = {
  title: 'GreenSentinel — Ride-Hailing Fraud Detection',
  description: 'GreenSentinel is a system aims to help Ride-Hailing platform to detect fraud earlier, process it more efficiently and improve overtime.',
}

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  return (
    <html lang="en" className={`${geistSans.variable} ${geistMono.variable} h-screen overflow-hidden antialiased`}>
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="" />
        <link
          href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&family=Material+Symbols+Outlined:wght,FILL@100..700,0..1&display=swap"
          rel="stylesheet"
        />
      </head>
      <body className="h-screen max-h-screen overflow-hidden flex flex-col font-sans bg-background text-foreground">
        <LocaleProvider>
        {localTestAuthentication() ? (
          <div className="flex-1 flex flex-col min-h-0 h-full overflow-hidden">
            {children}
          </div>
        ) : <ClerkProvider>
          <div className="flex-1 flex flex-col min-h-0 h-full overflow-hidden">
            {children}
          </div>
        </ClerkProvider>}
        </LocaleProvider>
      </body>
    </html>
  )
}
