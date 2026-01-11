import { ThemeToggle } from "@/components/ui/theme-toggle";
import { useTheme } from "@/contexts/ThemeContext";

export function Header() {
  const { theme } = useTheme();

  return (
    <header className="border-b bg-background">
      <div className="flex h-16 items-center justify-between px-6">
        <div className="flex items-center gap-3">
          <img
            src={theme === "light" ? "/logo-light.png" : "/logo-dark.png"}
            alt="Claude Deck"
            className="h-10 w-10"
          />
          <h1 className="text-2xl font-bold text-primary">Claude Deck</h1>
        </div>
        <ThemeToggle />
      </div>
    </header>
  )
}
