import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import { cn } from "@/lib/utils";
import { Sidebar } from "@/components/Sidebar";
import { ThemeProvider } from "@/components/theme-provider";

const inter = Inter({ subsets: ["latin"], variable: "--font-sans" });

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
    <html lang="en" className={cn("font-sans", inter.variable)} suppressHydrationWarning>
      <body className="min-h-screen bg-background text-foreground flex">
        <ThemeProvider
          attribute="class"
          defaultTheme="system"
          enableSystem
          disableTransitionOnChange
        >
          <Sidebar className="w-64 flex-shrink-0 hidden md:flex" />
          <main className="flex-1 min-w-0 p-8">
            {children}
          </main>
        </ThemeProvider>
      </body>
    </html>
  );
}
