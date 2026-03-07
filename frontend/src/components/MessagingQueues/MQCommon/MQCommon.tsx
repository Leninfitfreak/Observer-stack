import { Color } from '@signozhq/design-tokens';
import { Tooltip } from 'antd';
import { DefaultOptionType } from 'antd/es/select';
import { Info } from 'lucide-react';

import './MQCommon.styles.scss';

export function ComingSoon(): JSX.Element {
	return (
		<Tooltip
			title={
				<div>Messaging queue support is being prepared for a future release.</div>
			}
			placement="top"
			overlayClassName="tooltip-overlay"
		>
			<div className="coming-soon">
				<div className="coming-soon__text">Coming Soon</div>
				<div className="coming-soon__icon">
					<Info size={10} color={Color.BG_SIENNA_400} />
				</div>
			</div>
		</Tooltip>
	);
}

export function SelectMaxTagPlaceholder(
	omittedValues: Partial<DefaultOptionType>[],
): JSX.Element {
	return (
		<Tooltip title={omittedValues.map(({ value }) => value).join(', ')}>
			<span>+ {omittedValues.length} </span>
		</Tooltip>
	);
}

export function SelectLabelWithComingSoon({
	label,
}: {
	label: string;
}): JSX.Element {
	return (
		<div className="select-label-with-coming-soon">
			{label} <ComingSoon />
		</div>
	);
}
