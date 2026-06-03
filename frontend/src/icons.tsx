import React from "react";

interface IconProps extends React.SVGProps<SVGSVGElement> {
  width?: string | number;
  height?: string | number;
  color?: string;
}

export const PencilIcon: React.FC<IconProps> = ({ 
  width = "1em", 
  height = "1em", 
  color = "#111",
  style,
  ...props 
}) => (
  <svg
    width={width}
    height={height}
    viewBox="-1 -1 18 18"
    fill="none"
    overflow="visible"
    xmlns="http://www.w3.org/2000/svg"
    style={{ flexShrink: 0, ...style }}
    {...props}
  >
    <path
      d="M11.333 2.667a2.667 2.667 0 0 1 3.774 3.774l-8 8a2.667 2.667 0 0 1-1.886.78H2.667v-2.56a2.667 2.667 0 0 1 .78-1.886l8-8z"
      stroke={color}
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      fill="none"
    />
    <path
      d="M9.333 4.667l2 2"
      stroke={color}
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

export const ThreeDotsIcon: React.FC<IconProps> = ({ 
  width = "1em", 
  height = "1em", 
  color = "#6b7280",
  ...props 
}) => (
  <svg
    width={width}
    height={height}
    viewBox="0 0 16 16"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    {...props}
  >
    <circle cx="8" cy="3" r="1.5" fill={color} />
    <circle cx="8" cy="8" r="1.5" fill={color} />
    <circle cx="8" cy="13" r="1.5" fill={color} />
  </svg>
);

export const DeleteIcon: React.FC<IconProps> = ({ 
  width = "1em", 
  height = "1em", 
  color = "#ef4444",
  ...props 
}) => (
  <svg
    width={width}
    height={height}
    viewBox="0 0 16 16"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    {...props}
  >
    <path
      d="M2 4h12M5.333 4V2.667a1.333 1.333 0 0 1 1.334-1.334h2.666a1.333 1.333 0 0 1 1.334 1.334V4m2 0v9.333a1.333 1.333 0 0 1-1.334 1.334H4.667a1.333 1.333 0 0 1-1.334-1.334V4h9.334z"
      stroke={color}
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
    <path
      d="M6.667 7.333v4M9.333 7.333v4"
      stroke={color}
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

export const DownloadIcon: React.FC<IconProps & { strokeWidth?: string | number }> = ({ 
  width = "1em", 
  height = "1em", 
  color = "currentColor",
  strokeWidth = "2",
  ...props 
}) => (
  <svg
    width={width}
    height={height}
    viewBox="0 0 24 24"
    fill="none"
    stroke={color}
    strokeWidth={strokeWidth}
    strokeLinecap="round"
    strokeLinejoin="round"
    {...props}
  >
    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
    <polyline points="7 10 12 15 17 10" />
    <line x1="12" y1="15" x2="12" y2="3" />
  </svg>
);

export const SendIcon: React.FC<IconProps> = ({ 
  width = "1em", 
  height = "1em", 
  color = "currentColor",
  ...props 
}) => (
  <svg
    viewBox="0 0 24 24"
    fill="none"
    width={width}
    height={height}
    {...props}
  >
    <path
      d="M12 20 L12 4 M5 11 L12 4 L19 11"
      stroke={color}
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);


export const ChevronRightIcon: React.FC<IconProps> = ({ 
  width = "1em", 
  height = "1em", 
  color = "#6b7280",
  style,
  ...props 
}) => (
  <svg
    width={width}
    height={height}
    viewBox="0 0 16 16"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    style={style}
    {...props}
  >
    <path
      d="M6 12l4-4-4-4"
      stroke={color}
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      fill="none"
    />
  </svg>
);

export const ChevronLeftIcon: React.FC<IconProps> = ({ 
  width = "1em", 
  height = "1em", 
  color = "#6b7280",
  style,
  ...props 
}) => (
  <svg
    width={width}
    height={height}
    viewBox="0 0 16 16"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    style={style}
    {...props}
  >
    <path
      d="M10 4l-4 4 4 4"
      stroke={color}
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      fill="none"
    />
  </svg>
);

export const ChevronDownIcon: React.FC<IconProps> = ({ 
  width = "1em", 
  height = "1em", 
  color = "#6b7280",
  style,
  ...props 
}) => (
  <svg
    width={width}
    height={height}
    viewBox="0 0 16 16"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    style={style}
    {...props}
  >
    <path
      d="M4 6l4 4 4-4"
      stroke={color}
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      fill="none"
    />
  </svg>
);

export const PlusIcon: React.FC<IconProps> = ({ 
  width = "1em", 
  height = "1em", 
  color = "#111",
  style,
  ...props 
}) => (
  <svg
    width={width}
    height={height}
    viewBox="0 0 16 16"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    style={style}
    {...props}
  >
    <path
      d="M8 3v10M3 8h10"
      stroke={color}
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

export const XIcon: React.FC<IconProps> = ({ 
  width = "1em", 
  height = "1em", 
  color = "#111",
  style,
  ...props 
}) => (
  <svg
    width={width}
    height={height}
    viewBox="0 0 16 16"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    style={style}
    {...props}
  >
    <path
      d="M12 4L4 12M4 4l8 8"
      stroke={color}
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

export const SpinnerIcon: React.FC<IconProps> = ({ 
  width = "1em", 
  height = "1em", 
  color = "#3b82f6",
  style,
  ...props 
}) => (
  <svg
    width={width}
    height={height}
    viewBox="0 0 24 24"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    style={{
      animation: "spin 1s linear infinite",
      ...style
    }}
    {...props}
  >
    <circle
      cx="12"
      cy="12"
      r="10"
      stroke={color}
      strokeWidth="2"
      strokeOpacity="0.25"
      fill="none"
    />
    <path
      d="M12 2a10 10 0 0 1 10 10"
      stroke={color}
      strokeWidth="2"
      strokeLinecap="round"
      fill="none"
    />
  </svg>
);

export const PaperclipIcon: React.FC<IconProps> = ({
  width = "1em", height = "1em", color = "#111", style, ...props
}) => (
  <svg width={width} height={height} viewBox="0 0 24 24" fill="none" stroke={color}
    strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={style} {...props}>
    <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48" />
  </svg>
);

export const CheckCircleIcon: React.FC<IconProps> = ({
  width = "1em", height = "1em", color = "#10b981", style, ...props
}) => (
  <svg width={width} height={height} viewBox="0 0 24 24" fill="none" stroke={color}
    strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={style} {...props}>
    <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
    <polyline points="22 4 12 14.01 9 11.01" />
  </svg>
);

