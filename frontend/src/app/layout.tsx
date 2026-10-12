import type { Metadata } from "next";
import { Inter } from "next/font/google";
import localFont from "next/font/local";
import "./globals.css";
import { cn } from "@/lib/utils";
import { Sidebar } from "@/components/Sidebar";
import { MobileNav } from "@/components/MobileNav";
import { ThemeProvider } from "@/components/theme-provider";
import { Toaster } from "@/components/ui/toast";
import { AuthProvider } from "@/lib/auth/context";

const inter = Inter({ subsets: ["latin"], variable: "--font-sans" });
const geistMono = localFont({
  src: "./fonts/GeistMonoVF.woff",
  variable: "--font-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: "MST Operations Portal",
  description: "Manage midterm attendance eligibility, seating, and invigilation duty",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={cn("font-sans", inter.variable, geistMono.variable)} suppressHydrationWarning>
      <body className="min-h-screen bg-background text-foreground flex flex-col md:flex-row">
        <ThemeProvider
          attribute="class"
          defaultTheme="system"
          enableSystem
          disableTransitionOnChange
        >
          <AuthProvider>
            <MobileNav />
            <Sidebar className="w-64 flex-shrink-0 hidden md:flex" />
            <main className="flex-1 min-w-0 p-4 sm:p-6 md:p-8">
              {children}
            </main>
            <Toaster />
          </AuthProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}

