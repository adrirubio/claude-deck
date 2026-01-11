interface Props {
  source: Record<string, string>
}

export function ImageBlock({ source }: Props) {
  const imageData = source.data || ''
  const mediaType = source.media_type || 'image/png'

  return (
    <div className="border rounded-lg p-3 bg-gray-50/10">
      <img
        src={`data:${mediaType};base64,${imageData}`}
        alt="Session image"
        className="max-w-full h-auto rounded"
      />
    </div>
  )
}
