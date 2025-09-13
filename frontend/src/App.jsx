import { useState } from 'react'

// Components
function Header() {
  return (
    <header className="sticky top-0 z-50 bg-cream/95 backdrop-blur-sm border-b border-near-black/10">
      <div className="max-w-5xl mx-auto px-6 py-4 flex justify-between items-center">
        <h1 className="font-display text-xl font-medium tracking-tight">
          STYLE GENIE ✨
        </h1>
        <nav className="hidden sm:flex items-center space-x-6 text-sm">
          <a href="#about" className="text-near-black/70 hover:text-near-black transition-colors">
            About
          </a>
          <a href="#how" className="text-near-black/70 hover:text-near-black transition-colors">
            How it works
          </a>
        </nav>
      </div>
    </header>
  )
}

function Hero() {
  return (
    <section className="max-w-5xl mx-auto px-6 py-16 lg:py-24 text-center">
      <h1 className="font-display text-display font-light text-near-black mb-6 leading-none tracking-tight">
        Find Your <span className="text-tomato">Perfect</span> Piece
      </h1>
      <p className="text-lg text-near-black/70 max-w-2xl mx-auto leading-relaxed">
        Discover curated vintage furniture from Dutch marketplaces, 
        translated and matched to your unique style.
      </p>
    </section>
  )
}

function SearchCard({ onSearch, isLoading }) {
  const [query, setQuery] = useState('')
  const [minPrice, setMinPrice] = useState('')
  const [maxPrice, setMaxPrice] = useState('')
  const [radius, setRadius] = useState(10)

  const handleSubmit = (e) => {
    e.preventDefault()
    onSearch({
      query: query.trim(),
      min_price: minPrice ? parseInt(minPrice) : null,
      max_price: maxPrice ? parseInt(maxPrice) : null,
      radius_km: radius
    })
  }

  return (
    <div className="max-w-5xl mx-auto px-6 mb-16">
      <div className="bg-white rounded-2xl shadow-lg p-8 border border-near-black/5">
        <form onSubmit={handleSubmit} className="space-y-6">
          {/* Main search input */}
          <div>
            <label htmlFor="search" className="sr-only">Search for furniture</label>
            <input
              id="search"
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Find me a mid-century table under €150 in Amsterdam"
              className="w-full text-lg px-6 py-4 border border-near-black/20 rounded-2xl focus:outline-none focus:ring-2 focus:ring-tomato focus:border-transparent transition-all"
              required
            />
            <p className="text-sm text-near-black/50 mt-2">
              We search Dutch marketplaces and translate for you.
            </p>
          </div>

          {/* Price and radius filters */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div>
              <label htmlFor="minPrice" className="block text-sm font-medium text-near-black/70 mb-2">
                Min price (€)
              </label>
              <input
                id="minPrice"
                type="number"
                value={minPrice}
                onChange={(e) => setMinPrice(e.target.value)}
                className="w-full px-4 py-3 border border-near-black/20 rounded-xl focus:outline-none focus:ring-2 focus:ring-tomato focus:border-transparent"
                min="0"
              />
            </div>
            <div>
              <label htmlFor="maxPrice" className="block text-sm font-medium text-near-black/70 mb-2">
                Max price (€)
              </label>
              <input
                id="maxPrice"
                type="number"
                value={maxPrice}
                onChange={(e) => setMaxPrice(e.target.value)}
                className="w-full px-4 py-3 border border-near-black/20 rounded-xl focus:outline-none focus:ring-2 focus:ring-tomato focus:border-transparent"
                min="0"
              />
            </div>
            <div>
              <label htmlFor="radius" className="block text-sm font-medium text-near-black/70 mb-2">
                Radius ({radius} km)
              </label>
              <input
                id="radius"
                type="range"
                min="5"
                max="50"
                value={radius}
                onChange={(e) => setRadius(parseInt(e.target.value))}
                className="w-full h-3 bg-near-black/10 rounded-lg appearance-none cursor-pointer slider"
              />
            </div>
          </div>

          {/* Submit button */}
          <button
            type="submit"
            disabled={isLoading}
            className="w-full bg-near-black text-cream py-4 px-8 rounded-2xl text-lg font-medium hover:bg-tomato transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isLoading ? 'Searching...' : 'Summon'}
          </button>
        </form>
      </div>
    </div>
  )
}

function Chips({ onChipClick }) {
  const chips = [
    { label: 'Mid-century', nlTerms: 'teak stoel' },
    { label: 'Teak', nlTerms: 'teak' },
    { label: 'Velvet', nlTerms: 'velvet fluweel' },
    { label: 'Minimal', nlTerms: 'minimalistisch' },
    { label: 'Vintage', nlTerms: 'vintage retro' },
    { label: 'Industrial', nlTerms: 'industrieel staal' },
  ]

  return (
    <div className="max-w-5xl mx-auto px-6 mb-16">
      <div className="flex flex-wrap gap-3 justify-center">
        {chips.map((chip) => (
          <button
            key={chip.label}
            onClick={() => onChipClick(chip.label, chip.nlTerms)}
            className="px-4 py-2 bg-white border border-near-black/20 rounded-full text-sm font-medium hover:border-tomato hover:text-tomato transition-colors"
          >
            {chip.label}
          </button>
        ))}
      </div>
    </div>
  )
}

function ResultsGrid({ results, isLoading, error }) {
  if (error) {
    return (
      <div className="max-w-5xl mx-auto px-6 mb-16">
        <div className="text-center py-16 bg-white rounded-2xl border border-near-black/5">
          <div className="text-4xl mb-4">⚠️</div>
          <h3 className="text-xl font-medium text-near-black mb-2">Something went wrong</h3>
          <p className="text-near-black/70">{error}</p>
        </div>
      </div>
    )
  }

  if (isLoading) {
    return (
      <div className="max-w-5xl mx-auto px-6 mb-16">
        <div className="text-center py-16 bg-white rounded-2xl border border-near-black/5">
          <div className="text-4xl mb-4">🔮</div>
          <h3 className="text-xl font-medium text-near-black mb-2">Searching...</h3>
          <p className="text-near-black/70">Finding your perfect pieces</p>
        </div>
      </div>
    )
  }

  if (!results || results.length === 0) {
    return (
      <div className="max-w-5xl mx-auto px-6 mb-16">
        <div className="text-center py-16 bg-white rounded-2xl border border-near-black/5">
          <div className="text-4xl mb-4">✨</div>
          <h3 className="text-xl font-medium text-near-black mb-2">No gems yet</h3>
          <p className="text-near-black/70">Widen the price or tweak the vibe ✨</p>
        </div>
      </div>
    )
  }

  return (
    <div className="max-w-5xl mx-auto px-6 mb-16">
      <div className="mb-8 text-center">
        <h2 className="font-display text-2xl font-medium text-near-black mb-2">
          Found <span className="text-tomato">{results.length}</span> perfect pieces
        </h2>
      </div>
      
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {results.map((item, index) => (
          <div key={index} className="bg-white rounded-2xl overflow-hidden shadow-lg border border-near-black/5 hover:shadow-xl transition-shadow">
            {item.image && (
              <div className="aspect-square overflow-hidden bg-near-black/5">
                <img
                  src={item.image}
                  alt={item.title}
                  className="w-full h-full object-cover"
                  loading="lazy"
                />
              </div>
            )}
            <div className="p-6">
              <div className="flex items-start justify-between mb-3">
                <h3 className="font-medium text-near-black line-clamp-2 flex-1">
                  {item.title}
                </h3>
                <span className="bg-deep-green/10 text-deep-green text-xs px-2 py-1 rounded-full ml-2 flex-shrink-0">
                  {item.source}
                </span>
              </div>
              
              <div className="flex items-center justify-between text-sm text-near-black/70 mb-4">
                <span className="font-medium text-tomato">
                  €{item.price}
                </span>
                <div className="text-right">
                  {item.location && (
                    <div>📍 {item.location}</div>
                  )}
                  {item.distance_km && (
                    <div>{item.distance_km.toFixed(1)} km</div>
                  )}
                </div>
              </div>
              
              <a
                href={item.url}
                target="_blank"
                rel="noopener noreferrer"
                className="block w-full bg-near-black text-cream text-center py-3 rounded-xl font-medium hover:bg-tomato transition-colors"
              >
                View on {item.source}
              </a>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

function App() {
  const [results, setResults] = useState([])
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState(null)

  const searchItems = async (searchParams) => {
    setIsLoading(true)
    setError(null)
    
    try {
      const response = await fetch('/smart-search', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(searchParams)
      })

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`)
      }

      const data = await response.json()
      setResults(data.items || [])
    } catch (err) {
      setError('Failed to search. Please try again.')
      console.error('Search error:', err)
    } finally {
      setIsLoading(false)
    }
  }

  const handleChipClick = (label, nlTerms) => {
    searchItems({
      query: label,
      nl_terms: nlTerms,
      min_price: null,
      max_price: null,
      radius_km: 10
    })
  }

  return (
    <div className="min-h-screen bg-cream">
      <Header />
      <main>
        <Hero />
        <SearchCard onSearch={searchItems} isLoading={isLoading} />
        <Chips onChipClick={handleChipClick} />
        <ResultsGrid results={results} isLoading={isLoading} error={error} />
      </main>
    </div>
  )
}

export default App